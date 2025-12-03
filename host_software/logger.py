import serial
import serial.tools.list_ports
import csv
import time

# --- CONFIGURATION ---
FILENAME = "doe_run_safe.csv"
BAUD_RATE = 115200

def get_pico_port():
    ports = list(serial.tools.list_ports.comports())
    for p in ports:
        if "USB Serial Device" in p.description or "Pi" in p.manufacturer:
            return p.device
    return None

def main():
    print("--- Robust Data Logger ---")
    
    port = get_pico_port()
    if not port:
        port = input("Enter COM port manually (e.g. COM4): ").strip()
    
    print(f"Connecting to {port}...")
    
    try:
        ser = serial.Serial(port, BAUD_RATE, timeout=1)
        time.sleep(1) # Let connection settle
        print(f"Connected! Saving to '{FILENAME}'")
        
        # 1. Open CSV with DictWriter
        with open(FILENAME, mode='w', newline='') as f:
            # Define exact column names
            fieldnames = ["Time_Sec", "Raw_Force"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            
            # Write the header once
            writer.writeheader()
            
            start_time = time.time()
            
            # 2. Recording Loop
            while True:
                if ser.in_waiting:
                    try:
                        # Read and clean the line
                        line = ser.readline().decode('utf-8', errors='ignore').strip()
                        
                        # Only process lines that look correct
                        if line.startswith("Force:"):
                            # Parse the Number
                            parts = line.split(":")
                            if len(parts) < 2: continue # Skip malformed lines
                            
                            raw_val_str = parts[1].strip()
                            if not raw_val_str: continue # Skip empty values
                            
                            current_force = int(raw_val_str)
                            
                            # Calculate Time
                            current_time = round(time.time() - start_time, 3)
                            
                            # Print to Console (Verify columns aren't swapping here!)
                            print(f"Time: {current_time} -> Force: {current_force}")
                            
                            # 3. Write to CSV using Explicit Keys
                            # This makes swapping impossible
                            writer.writerow({
                                "Time_Sec": current_time, 
                                "Raw_Force": current_force
                            })
                            
                            # Ensure it writes to disk immediately
                            f.flush()
                            
                    except ValueError:
                        pass # Skip garbage data

    except KeyboardInterrupt:
        print("\nStopped.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
