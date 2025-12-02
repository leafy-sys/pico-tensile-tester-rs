#![no_std]
#![no_main]

use bsp::entry;
use defmt::*;
use defmt_rtt as _;
use panic_probe as _;
use rp_pico as bsp;

use bsp::hal::{
    clocks::{init_clocks_and_plls, Clock},
    pac,
    sio::Sio,
    watchdog::Watchdog,
    usb::UsbBus,
};

use hx711::Hx711;

// --- USB IMPORTS ---
use usb_device::{class_prelude::*, prelude::*};
use usbd_serial::SerialPort;
use ufmt::{uWrite, uwriteln};

// --- FIXED GLUE CODE (Newtype Pattern) ---
// 1. Define a wrapper struct that WE own.
struct SerialWrapper<'a, B: usb_device::bus::UsbBus>(SerialPort<'a, B>);

// 2. Implement uWrite for OUR wrapper.
impl<B: usb_device::bus::UsbBus> uWrite for SerialWrapper<'_, B> {
    type Error = ();
    fn write_str(&mut self, s: &str) -> Result<(), Self::Error> {
        // We delegate the write to the inner SerialPort (self.0)
        let _ = self.0.write(s.as_bytes());
        Ok(())
    }
}
// -----------------------------------------

#[entry]
fn main() -> ! {
    let mut pac = pac::Peripherals::take().unwrap();
    let core = pac::CorePeripherals::take().unwrap();
    let mut watchdog = Watchdog::new(pac.WATCHDOG);
    let sio = Sio::new(pac.SIO);

    let external_xtal_freq_hz = 12_000_000u32;
    let clocks = init_clocks_and_plls(
        external_xtal_freq_hz,
        pac.XOSC,
        pac.CLOCKS,
        pac.PLL_SYS,
        pac.PLL_USB,
        &mut pac.RESETS,
        &mut watchdog,
    ).ok().unwrap();

    // --- USB SETUP ---
    let usb_bus = UsbBusAllocator::new(UsbBus::new(
        pac.USBCTRL_REGS,
        pac.USBCTRL_DPRAM,
        clocks.usb_clock,
        true,
        &mut pac.RESETS,
    ));

    let serial = SerialPort::new(&usb_bus);
    
    // WRAP the serial port in our new struct so we can print to it!
    let mut serial_wrapper = SerialWrapper(serial);

    let mut usb_dev = UsbDeviceBuilder::new(&usb_bus, UsbVidPid(0x16c0, 0x27dd))
        .device_class(2)
        .build();

    // --- LOAD CELL SETUP ---
    let pins = bsp::Pins::new(
        pac.IO_BANK0, pac.PADS_BANK0, sio.gpio_bank0, &mut pac.RESETS,
    );
    
    let dt_pin = pins.gpio16.into_floating_input();
    let sck_pin = pins.gpio17.into_push_pull_output();

    let delay = cortex_m::delay::Delay::new(core.SYST, clocks.system_clock.freq().to_Hz());

    let mut load_cell = Hx711::new(delay, dt_pin, sck_pin).ok().unwrap();

    let mut offset = 0;
    for _ in 0..10 {
        if let Ok(reading) = load_cell.retrieve() {
            offset = reading;
            break;
        }
        cortex_m::asm::delay(1_000_000);
    }

    loop {
        // --- 1. Poll USB ---
        // We have to access the inner SerialPort using .0
        if usb_dev.poll(&mut [&mut serial_wrapper.0]) {
            // Poll happens here
        }

        // --- 2. Read Sensor ---
        match load_cell.retrieve() {
            Ok(value) => {
                let clean_value = value - offset;
                
                // --- 3. Send to PC ---
                // Now we can use uwriteln! on our wrapper!
                let _ = uwriteln!(serial_wrapper, "Force: {}\r", clean_value);
            }
            Err(_) => { }
        }

        cortex_m::asm::delay(13_300_000); 
    }
}
