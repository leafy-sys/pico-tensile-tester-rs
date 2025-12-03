#![no_std]
#![no_main]

use bsp::entry;
use defmt_rtt as _;
use panic_probe as _;
use rp_pico as bsp;

use bsp::hal::{
    clocks::{init_clocks_and_plls, Clock},
    pac,
    sio::Sio,
    usb::UsbBus,
    watchdog::Watchdog,
    Timer, // Import Timer
};

use fugit::ExtU64;
use hx711::Hx711; // Import the time extension trait

// --- USB IMPORTS ---
use ufmt::{uWrite, uwriteln};
use usb_device::{class_prelude::*, prelude::*};
use usbd_serial::SerialPort;

// --- GLUE CODE ---
struct SerialWrapper<'a, B: usb_device::bus::UsbBus>(SerialPort<'a, B>);

impl<B: usb_device::bus::UsbBus> uWrite for SerialWrapper<'_, B> {
    type Error = ();
    fn write_str(&mut self, s: &str) -> Result<(), Self::Error> {
        let _ = self.0.write(s.as_bytes());
        Ok(())
    }
}
// ----------------

#[entry]
fn main() -> ! {
    let mut pac = pac::Peripherals::take().unwrap();
    let core = pac::CorePeripherals::take().unwrap();
    let mut watchdog = Watchdog::new(pac.WATCHDOG);
    let sio = Sio::new(pac.SIO);

    let external_xtal_freq_hz = 12_000_000u32;

    // 1. INITIALIZE CLOCKS FIRST
    let clocks = init_clocks_and_plls(
        external_xtal_freq_hz,
        pac.XOSC,
        pac.CLOCKS,
        pac.PLL_SYS,
        pac.PLL_USB,
        &mut pac.RESETS,
        &mut watchdog,
    )
    .ok()
    .unwrap();

    // 2. NOW INITIALIZE TIMER (Because it needs &clocks)
    let timer = Timer::new(pac.TIMER, &mut pac.RESETS, &clocks);

    // --- USB SETUP ---
    let usb_bus = UsbBusAllocator::new(UsbBus::new(
        pac.USBCTRL_REGS,
        pac.USBCTRL_DPRAM,
        clocks.usb_clock,
        true,
        &mut pac.RESETS,
    ));

    let serial = SerialPort::new(&usb_bus);
    let mut serial_wrapper = SerialWrapper(serial);

    let mut usb_dev = UsbDeviceBuilder::new(&usb_bus, UsbVidPid(0x16c0, 0x27dd))
        .device_class(2)
        .build();

    // --- LOAD CELL SETUP ---
    let pins = bsp::Pins::new(
        pac.IO_BANK0,
        pac.PADS_BANK0,
        sio.gpio_bank0,
        &mut pac.RESETS,
    );

    let dt_pin = pins.gpio16.into_floating_input();
    let sck_pin = pins.gpio17.into_push_pull_output();

    // Create a delay for the HX711 initialization
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

    // Set the first target time (Now + 100ms)
    // FIX: Use 100u64 so .millis() works!
    let mut next_read = timer.get_counter() + 100u64.millis();

    loop {
        // --- 1. Poll USB ---
        usb_dev.poll(&mut [&mut serial_wrapper.0]);

        // --- 2. Check Timer (Non-blocking!) ---
        if timer.get_counter() >= next_read {
            // Schedule next read
            next_read = timer.get_counter() + 100u64.millis();

            // --- 3. Read Sensor ---
            if let Ok(value) = load_cell.retrieve() {
                let clean_value = value - offset;
                let _ = uwriteln!(serial_wrapper, "Force: {}\r", clean_value);
            }
        }
    }
}

// Testing
