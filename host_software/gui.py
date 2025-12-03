import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import serial
import serial.tools.list_ports
import threading
import queue
import time
import csv
import os
from collections import deque

# --- Matplotlib Imports ---
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
import matplotlib.animation as animation

# --- THEME COLORS ---
COLOR_BG = "#1E1E1E"        # Dark Charcoal
COLOR_FG = "#E0E0E0"        # Light Grey
COLOR_ACCENT = "#32CD32"    # Lime Green
COLOR_GRAPH_BG = "#2B2B2B"  # Slightly lighter grey for graph
COLOR_GRID = "#444444"      # Dim grey for grid lines

class TensileTesterSuite:
    def __init__(self, root):
        self.root = root
        self.root.title("Whirlpool Tensile Lab Suite")
        self.root.geometry("1100x750")
        self.root.configure(bg=COLOR_BG) # Set main window background
        
        # --- Variables ---
        self.serial_port = None
        self.is_running = False
        self.is_recording = False
        self.data_queue = queue.Queue()
        self.smooth_buffer = deque(maxlen=10)
        
        self.time_data = []
        self.force_data = []
        self.start_time = 0
        self.csv_file = None
        self.csv_writer = None
        
        self.save_dir = os.getcwd()
        self.tare_offset = 0 # Python-side Tare value
        self.current_raw = 0 # Keep track of raw value for taring
        
        # --- STYLE CONFIGURATION ---
        self.setup_styles()

        # --- GUI LAYOUT ---
        
        # 1. Top Control Bar
        control_frame = ttk.LabelFrame(root, text="System Control", style="Dark.TLabelframe")
        control_frame.pack(fill="x", padx=10, pady=5)
        
        # Connection
        ttk.Label(control_frame, text="Port:", style="Dark.TLabel").pack(side="left", padx=5)
        self.port_combo = ttk.Combobox(control_frame, values=self.get_ports(), width=10)
        self.port_combo.pack(side="left", padx=5)
        
        self.connect_btn = tk.Button(control_frame, text="CONNECT", bg="#444", fg=COLOR_FG, 
                                     command=self.toggle_connection, relief="flat", padx=10)
        self.connect_btn.pack(side="left", padx=5, pady=5)
        
        # Calibration & Tare
        ttk.Separator(control_frame, orient="vertical").pack(side="left", fill="y", padx=15, pady=5)
        
        ttk.Label(control_frame, text="Cal Factor:", style="Dark.TLabel").pack(side="left", padx=5)
        self.cal_var = tk.StringVar(value="2180.0")
        self.cal_entry = ttk.Entry(control_frame, textvariable=self.cal_var, width=8)
        self.cal_entry.pack(side="left", padx=5)
        
        # TARE BUTTON (New!)
        self.tare_btn = tk.Button(control_frame, text="TARE (ZERO)", bg="#555", fg=COLOR_ACCENT, 
                                  command=self.tare_scale, relief="flat", padx=10, font=("Arial", 9, "bold"))
        self.tare_btn.pack(side="left", padx=15, pady=5)

        # 2. Main Content Area
        content_frame = tk.Frame(root, bg=COLOR_BG)
        content_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        # --- Left Side: The Graph ---
        graph_frame = ttk.LabelFrame(content_frame, text="Stress / Strain Curve", style="Dark.TLabelframe")
        graph_frame.pack(side="left", fill="both", expand=True)
        
        # Matplotlib Setup (Dark Mode)
        self.fig = Figure(figsize=(5, 4), dpi=100, facecolor=COLOR_GRAPH_BG)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_facecolor(COLOR_GRAPH_BG)
        
        # Color the axes and labels
        self.ax.spines['bottom'].set_color(COLOR_FG)
        self.ax.spines['top'].set_color(COLOR_FG)
        self.ax.spines['left'].set_color(COLOR_FG)
        self.ax.spines['right'].set_color(COLOR_FG)
        self.ax.tick_params(axis='x', colors=COLOR_FG)
        self.ax.tick_params(axis='y', colors=COLOR_FG)
        self.ax.yaxis.label.set_color(COLOR_FG)
        self.ax.xaxis.label.set_color(COLOR_FG)
        self.ax.title.set_color(COLOR_FG)
        
        self.ax.set_title("Live Force Data")
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Force (kg)")
        self.ax.grid(True, color=COLOR_GRID, linestyle='--')
        
        # The Line (Green!)
        self.line, = self.ax.plot([], [], color=COLOR_ACCENT, linewidth=2)
        
        # Embed Graph
        self.canvas = FigureCanvasTkAgg(self.fig, master=graph_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(side="top", fill="both", expand=True)
        
        # --- Right Side: Live Values & Settings ---
        right_panel = tk.Frame(content_frame, width=250, bg=COLOR_BG)
        right_panel.pack(side="right", fill="y", padx=10)
        
        # Big Number Display
        display_frame = ttk.LabelFrame(right_panel, text="Current Reading", style="Dark.TLabelframe")
        display_frame.pack(fill="x", pady=10)
        
        # Make the number BIG and GREEN
        self.val_label = tk.Label(display_frame, text="0.00", font=("Consolas", 48, "bold"), 
                                  bg=COLOR_BG, fg=COLOR_ACCENT, width=8)
        self.val_label.pack(anchor="center", pady=10)
        
        self.unit_label = ttk.Label(display_frame, text="kg", style="Dark.TLabel")
        self.unit_label.pack(anchor="center", pady=(0,10))

        # Peak Force Display
        peak_frame = ttk.LabelFrame(right_panel, text="Peak Force", style="Dark.TLabelframe")
        peak_frame.pack(fill="x", pady=10)

        self.peak_label = tk.Label(peak_frame, text="0.00", font=("Consolas", 30, "bold"),
                                   bg=COLOR_BG, fg="#FF8C00")
        self.peak_label.pack(anchor="center", pady=5)

        self.peak_unit_label = ttk.Label(peak_frame, text="kg", style="Dark.TLabel")
        self.peak_unit_label.pack(anchor="center", pady=(0,5))

        self.peak_force = 0.0

        # File Settings
        file_frame = ttk.LabelFrame(right_panel, text="Test Configuration", style="Dark.TLabelframe")
        file_frame.pack(fill="x", pady=10)
        
        ttk.Label(file_frame, text="Filename:", style="Dark.TLabel").pack(anchor="w", padx=5)
        self.filename_var = tk.StringVar(value="test_run_01")
        ttk.Entry(file_frame, textvariable=self.filename_var).pack(fill="x", padx=5, pady=2)
        
        tk.Button(file_frame, text="Browse Folder...", command=self.browse_folder, 
                  bg="#444", fg=COLOR_FG, relief="flat").pack(fill="x", padx=5, pady=5)
        
        self.dir_label = ttk.Label(file_frame, text=self.save_dir, style="Dark.TLabel", wraplength=200)
        self.dir_label.pack(fill="x", padx=5, pady=5)

        # BIG RECORD BUTTON
        self.record_btn = tk.Button(right_panel, text="START RECORDING", command=self.toggle_recording, 
                                    state="disabled", bg="#333", fg="white", font=("Arial", 12, "bold"),
                                    activebackground=COLOR_ACCENT, activeforeground="black", height=2)
        self.record_btn.pack(fill="x", pady=20)
        
        # Load / Replay
        ttk.Separator(right_panel, orient="horizontal").pack(fill="x", pady=10)
        tk.Button(right_panel, text="Open Existing CSV", command=self.load_csv_file,
                  bg="#444", fg=COLOR_FG, relief="flat").pack(fill="x", pady=5)

        # --- Timers ---
        self.root.after(10, self.process_queue)
        self.root.after(100, self.update_plot)

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam') # 'clam' allows cleaner color customization
        
        style.configure("Dark.TLabel", background=COLOR_BG, foreground=COLOR_FG, font=("Arial", 10))
        style.configure("Dark.TLabelframe", background=COLOR_BG, foreground=COLOR_FG, bordercolor=COLOR_GRID)
        style.configure("Dark.TLabelframe.Label", background=COLOR_BG, foreground=COLOR_ACCENT, font=("Arial", 10, "bold"))
        style.configure("TCombobox", fieldbackground="#333", background="#333", foreground="white")
        style.configure("TEntry", fieldbackground="#333", foreground="white")

    # --- Tare Logic ---
    def tare_scale(self):
        """Zero the scale by saving the current raw offset."""
        self.tare_offset = self.current_raw
        # If we are simply adding to the existing Rust tare, this works perfectly.
        # Force Label should go to 0 immediately.

    # --- Connection ---
    def get_ports(self):
        return [p.device for p in serial.tools.list_ports.comports()]
    
    def toggle_connection(self):
        if not self.serial_port:
            try:
                port = self.port_combo.get()
                self.serial_port = serial.Serial(port, 115200, timeout=1)
                self.is_running = True
                self.connect_btn.config(text="DISCONNECT", bg=COLOR_ACCENT, fg="black")
                self.record_btn.config(state="normal", bg="#444") # Enable Record
                
                self.time_data = []
                self.force_data = []
                self.thread = threading.Thread(target=self.serial_loop, daemon=True)
                self.thread.start()
            except Exception as e:
                messagebox.showerror("Error", str(e))
        else:
            self.is_running = False
            if self.serial_port: self.serial_port.close()
            self.serial_port = None
            self.connect_btn.config(text="CONNECT", bg="#444", fg=COLOR_FG)
            self.record_btn.config(state="disabled", bg="#333", text="START RECORDING")
            self.is_recording = False

    def toggle_recording(self):
        if not self.is_recording:
            # --- START RECORDING ---
            
            # 1. Reset Peak for the NEW test
            # This clears the old value only when you are ready to go again.
            self.peak_force = 0.0
            self.peak_label.config(text="0.00")

            # Setup Filename
            name = self.filename_var.get()
            if not name.endswith(".csv"): name += ".csv"
            fullpath = os.path.join(self.save_dir, name)
            
            try:
                self.csv_file = open(fullpath, 'w', newline='')
                self.csv_writer = csv.DictWriter(self.csv_file, fieldnames=["Time_Sec", "Force_Kg"])
                self.csv_writer.writeheader()
                
                # Reset Graph
                self.time_data = []
                self.force_data = []
                self.ax.clear()
                self.ax.set_facecolor(COLOR_GRAPH_BG)
                self.ax.grid(True, color=COLOR_GRID, linestyle='--')
                self.line, = self.ax.plot([], [], color=COLOR_ACCENT, linewidth=2)
                
                self.start_time = time.time()
                self.is_recording = True
                self.record_btn.config(text="STOP RECORDING", bg="#FF4444", fg="white")
            except Exception as e:
                messagebox.showerror("Error", str(e))
        else:
            # --- STOP RECORDING ---
            self.is_recording = False
            if self.csv_file: self.csv_file.close()
            self.record_btn.config(text="START RECORDING", bg="#333", fg="white")
            
            # --- SAVE SUMMARY (New Feature) ---
            # This saves the peak to a master file, but leaves the GUI display alone!
            self.save_summary()
            
            messagebox.showinfo("Test Complete", f"Peak Force: {self.peak_force:.2f} kg\n\nData and Summary Saved.")

    def save_summary(self):
        """Appends the test result to a master summary CSV."""
        summary_path = os.path.join(self.save_dir, "doe_summary.csv")
        file_exists = os.path.isfile(summary_path)
        
        try:
            with open(summary_path, 'a', newline='') as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(["Filename", "Peak_Force_Kg", "Date_Time"])
                
                writer.writerow([
                    self.filename_var.get(),
                    f"{self.peak_force:.2f}",
                    time.strftime("%Y-%m-%d %H:%M:%S")
                ])
        except Exception as e:
            print(f"Summary Error: {e}")

    # --- Worker Thread ---
    def serial_loop(self):
        while self.is_running and self.serial_port.is_open:
            try:
                if self.serial_port.in_waiting:
                    line = self.serial_port.readline().decode('utf-8', errors='ignore').strip()
                    if line.startswith("Force:"):
                        # Extract Raw Data from Pico
                        self.current_raw = int(line.split(":")[1].strip())
                        self.data_queue.put(self.current_raw)
            except: pass
            time.sleep(0.001)

    # --- Data Processing ---
    def process_queue(self):
        try:
            while True:
                # 1. Get RAW value from Pico
                raw_val = self.data_queue.get_nowait()
                
                self.smooth_buffer.append(raw_val)
                if len(self.smooth_buffer) > 0:
                    avg_raw = sum(self.smooth_buffer) / len(self.smooth_buffer)
                else:
                    avg_raw = raw_val
                
                tared_val = avg_raw - self.tare_offset
                
                # 3. Apply Calibration
                try: cal_factor = float(self.cal_var.get())
                except: cal_factor = 1.0
                if cal_factor == 0: cal_factor = 1.0
                
                force_kg = tared_val / cal_factor

                if abs(force_kg) > self.peak_force:
                    self.peak_force = abs(force_kg)
                    self.peak_label.config(text=f"{self.peak_force:.2f}")
                
                # 4. Update Display
                self.val_label.config(text=f"{force_kg:.2f}")
                
                # 5. Record/Graph
                if self.is_recording:
                    elapsed = round(time.time() - self.start_time, 3)
                    self.time_data.append(elapsed)
                    self.force_data.append(force_kg)
                    self.csv_writer.writerow({"Time_Sec": elapsed, "Force_Kg": force_kg})
                    
        except queue.Empty: pass
        self.root.after(10, self.process_queue)

    def update_plot(self):
        if self.is_recording and len(self.time_data) > 0:
            self.line.set_data(self.time_data, self.force_data)
            self.ax.relim()
            self.ax.autoscale_view()
            self.canvas.draw()
        self.root.after(100, self.update_plot)

    def browse_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.save_dir = folder
            self.dir_label.config(text=self.save_dir)

    def load_csv_file(self):
        filepath = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv")])
        if not filepath: return
        try:
            times, forces = [], []
            with open(filepath, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    times.append(float(row.get("Time_Sec", 0)))
                    forces.append(float(row.get("Force_Kg", 0)))
            
            self.ax.clear()
            self.ax.set_facecolor(COLOR_GRAPH_BG)
            self.ax.grid(True, color=COLOR_GRID, linestyle='--')
            self.ax.plot(times, forces, color=COLOR_ACCENT, linewidth=2)
            self.canvas.draw()
        except Exception as e:
            messagebox.showerror("Error", str(e))

if __name__ == "__main__":
    root = tk.Tk()
    app = TensileTesterSuite(root)
    root.mainloop()
