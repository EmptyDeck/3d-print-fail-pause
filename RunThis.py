import tkinter as tk
from tkinter import ttk
import cv2
import numpy as np
from PIL import Image, ImageTk
from monitor import Monitor  # Assuming monitor.py is in the same directory
# Assuming email_sender.py is in the same directory
from email_sender import send_alert_email
import datetime

# --- Configuration ---
CANVAS_W = 410
BLEND_ALPHA = 0.4
sensitivity = 30  # Initial sensitivity
consecutive_threshold = 3
MINT_BGR = (201, 252, 157)
ALERT_BGR = (0, 0, 255)
BOX_THICKNESS = 4

# --- GPIO and Filament Sensor Setup ---
FILAMENT_SENSOR_PIN = 22
PRINTER_PAUSE_PIN = 17

GPIO_AVAILABLE = False
try:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(PRINTER_PAUSE_PIN, GPIO.OUT)
    GPIO.setup(FILAMENT_SENSOR_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    GPIO_AVAILABLE = True
    print("RPi.GPIO initialized successfully.")

    def set_printer_state_hw(run_printer: bool):
        if run_printer:
            GPIO.output(PRINTER_PAUSE_PIN, GPIO.LOW)
            print(
                f"GPIO {PRINTER_PAUSE_PIN} set to LOW (0 V) - Printer Running")
        else:
            GPIO.output(PRINTER_PAUSE_PIN, GPIO.HIGH)
            print(f"GPIO {PRINTER_PAUSE_PIN} set to HIGH - Printer Paused")

    def is_filament_present_hw():
        return GPIO.input(FILAMENT_SENSOR_PIN) == GPIO.LOW

except ImportError:
    print("RPi.GPIO not found. Running in simulation mode for GPIO.")

    def set_printer_state_hw(run_printer: bool):
        if run_printer:
            print(
                f"SIMULATE: GPIO {PRINTER_PAUSE_PIN} set to LOW (0 V) - Printer Running")
        else:
            print(
                f"SIMULATE: GPIO {PRINTER_PAUSE_PIN} set to HIGH - Printer Paused")

    def is_filament_present_hw():
        return True


class App:
    def __init__(self, root):
        self.root = root
        root.title("Live Extraction & Printer Monitor")
        root.geometry("480x800")
        root.resizable(False, False)

        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            raise RuntimeError("Cannot open camera")
        fw = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        fh = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        self.CANVAS_H = int(CANVAS_W * fh / fw)
        self.sx = fw / CANVAS_W
        self.sy = fh / self.CANVAS_H

        self.canvas = tk.Canvas(root, width=CANVAS_W,
                                height=self.CANVAS_H, bg="black")
        self.canvas.place(x=35, y=18)

        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Custom.TButton', font=('TkDefaultFont', 30))

        self.sensitivity_label = tk.Label(
            root, text=f"Sensitivity: {sensitivity}%", font=('TkDefaultFont', 20))
        self.sensitivity_label.place(x=70, y=310)

        self.increase_btn = ttk.Button(
            root, text="+", command=self.increase_sensitivity, style='Custom.TButton')
        self.increase_btn.place(x=250, y=300, width=50, height=50)

        self.decrease_btn = ttk.Button(
            root, text="-", command=self.decrease_sensitivity, style='Custom.TButton')
        self.decrease_btn.place(x=310, y=300, width=50, height=50)

        initial_filament_status = "Filament: Initializing..." if GPIO_AVAILABLE else "Filament: N/A (No GPIO)"
        self.filament_status_label = tk.Label(
            root, text=initial_filament_status, font=('TkDefaultFont', 16))
        self.filament_status_label.place(x=35, y=self.CANVAS_H + 25)

        self.start_btn = ttk.Button(
            root, text="Start Monitoring", command=self.toggle_running, style='Custom.TButton')
        self.start_btn.place(x=15, y=370, width=450, height=180)

        self.pause_btn = ttk.Button(
            root, text="Pause 3D Printer", command=self.toggle_user_pause, style='Custom.TButton')
        self.pause_btn.place(x=15, y=570, width=450, height=180)

        # Settings button for email configuration
        self.settings_btn = tk.Button(
            root, text="Settings", command=self.open_settings, font=('TkDefaultFont', 10))
        self.settings_btn.place(x=400, y=750, width=70, height=30)

        self.canvas.bind("<ButtonPress-1>", self.on_mouse_down)
        self.canvas.bind("<B1-Motion>", self.on_mouse_move)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_up)

        self.drawing = False
        self.ix = self.iy = self.fx = self.fy = 0
        self.roi_canvas = (0, 0, 0, 0)
        self.roi_defined = False
        self.running = False
        self.printer_paused_by_user = False
        self.printer_paused_by_filament = False
        self.filament_alert_email_sent = False

        # Email credentials
        self.sender_email = None
        self.sender_password = None
        self.recipient_email = None

        self.monitor = Monitor(sensitivity, consecutive_threshold,
                               BLEND_ALPHA, MINT_BGR, ALERT_BGR, BOX_THICKNESS)
        self._apply_printer_pause_state()
        self.photo = None
        self.update_frame()

    def increase_sensitivity(self):
        self.monitor.sensitivity += 5
        self.sensitivity_label.config(
            text=f"Sensitivity: {self.monitor.sensitivity}%")

    def decrease_sensitivity(self):
        if self.monitor.sensitivity > 5:
            self.monitor.sensitivity -= 5
            self.sensitivity_label.config(
                text=f"Sensitivity: {self.monitor.sensitivity}%")

    def on_mouse_down(self, event):
        if not self.running:
            self.roi_defined = False
            self.drawing = True
            self.ix = event.x
            self.iy = event.y
            self.fx = event.x
            self.fy = event.y

    def on_mouse_move(self, event):
        if self.drawing:
            self.fx = event.x
            self.fy = event.y

    def on_mouse_up(self, event):
        if self.drawing:
            self.drawing = False
            self.fx = event.x
            self.fy = event.y
            x0, y0 = min(self.ix, self.fx), min(self.iy, self.fy)
            x1, y1 = max(self.ix, self.fx), max(self.iy, self.fy)
            if x1 - x0 > 5 and y1 - y0 > 5:
                self.roi_canvas = (x0, y0, x1 - x0, y1 - y0)
                self.roi_defined = True
            else:
                self.roi_defined = False

    def toggle_running(self):
        if not self.roi_defined and not self.running:
            print("Please define an ROI by dragging on the video feed before starting.")
            return
        self.running = not self.running
        self.start_btn.config(
            text="Stop Monitoring" if self.running else "Start Monitoring")
        if self.running:
            print("Monitoring started.")
            self.monitor.reset()
        else:
            print("Monitoring stopped.")
            self.printer_paused_by_user = False
            self.printer_paused_by_filament = False
            self.filament_alert_email_sent = False
            self.pause_btn.config(text="Pause 3D Printer")
            self._apply_printer_pause_state()

    def toggle_user_pause(self):
        self.printer_paused_by_user = not self.printer_paused_by_user
        self.pause_btn.config(
            text="Resume 3D Printer" if self.printer_paused_by_user else "Pause 3D Printer")
        if self.printer_paused_by_user:
            print("Printer pause requested by user.")
        else:
            print("Printer resume requested by user.")
        self._apply_printer_pause_state()

    def _apply_printer_pause_state(self):
        if self.printer_paused_by_user or self.printer_paused_by_filament:
            set_printer_state_hw(False)
        else:
            set_printer_state_hw(True)

    def open_settings(self):
        settings_window = tk.Toplevel(self.root)
        settings_window.title("Email Settings")
        settings_window.geometry("300x200")

        tk.Label(settings_window, text="Sender Email:").pack()
        sender_email_entry = tk.Entry(settings_window)
        sender_email_entry.pack()
        sender_email_entry.insert(0, self.sender_email or "")

        tk.Label(settings_window, text="Sender Password:").pack()
        sender_password_entry = tk.Entry(settings_window, show="*")
        sender_password_entry.pack()
        sender_password_entry.insert(0, self.sender_password or "")

        tk.Label(settings_window, text="Recipient Email:").pack()
        recipient_email_entry = tk.Entry(settings_window)
        recipient_email_entry.pack()
        recipient_email_entry.insert(0, self.recipient_email or "")

        def save_settings():
            self.sender_email = sender_email_entry.get()
            self.sender_password = sender_password_entry.get()
            self.recipient_email = recipient_email_entry.get()
            settings_window.destroy()

        save_btn = tk.Button(settings_window, text="Save",
                             command=save_settings)
        save_btn.pack()

    def _check_filament_status(self):
        if not GPIO_AVAILABLE:
            self.filament_status_label.config(
                text="Filament sensor not used" if self.running else "Filament: N/A (No GPIO)", fg="black")
            return

        if not self.running:
            self.filament_status_label.config(
                text="Filament: Not Tracking", fg="black")
            if self.printer_paused_by_filament:
                print(
                    "Monitoring stopped while printer was paused by filament. Resetting filament pause state.")
                self.printer_paused_by_filament = False
                self.filament_alert_email_sent = False
                self._apply_printer_pause_state()
            return

        filament_present = is_filament_present_hw()
        if not filament_present:
            self.filament_status_label.config(
                text="Filament: RAN OUT!", fg="red")
            if not self.printer_paused_by_filament:
                print("FILAMENT RUN-OUT DETECTED!")
                self.printer_paused_by_filament = True
                if not self.filament_alert_email_sent:
                    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    email_subject = "3D Printer Alert: Filament Ran Out"
                    email_body = f"""
                    <html>
                      <body>
                        <h2>3\partial Printer Alert: Filament Ran Out</h2>
                        <p>The 3D printer's filament sensor detected no filament at {timestamp}.</p>
                        <p>The printer has been paused.</p>
                      </body>
                    </html>
                    """
                    if self.sender_email and self.sender_password and self.recipient_email:
                        try:
                            send_alert_email(
                                from_email=self.sender_email,
                                password=self.sender_password,
                                to_email=self.recipient_email,
                                subject=email_subject,
                                body=email_body,
                                image_path=None
                            )
                            print("Filament run-out email notification sent.")
                            self.filament_alert_email_sent = True
                        except Exception as e:
                            print(f"Error sending filament run-out email: {e}")
                            self.filament_alert_email_sent = True
                    else:
                        print(
                            "Email credentials not set, cannot send filament run-out email.")
                        self.filament_alert_email_sent = True
                self._apply_printer_pause_state()
        else:
            self.filament_status_label.config(
                text="Filament: Present", fg="green")
            if self.printer_paused_by_filament:
                print("Filament re-detected. Clearing filament pause.")
                self.printer_paused_by_filament = False
                self.filament_alert_email_sent = False
                self._apply_printer_pause_state()

    def update_frame(self):
        ret, frame = self.cap.read()
        if not ret:
            self.root.after(100, self.update_frame)
            return

        disp = frame.copy()
        self._check_filament_status()

        if self.running:
            disp, alert_triggered, db = self.monitor.process_frame(
                frame, self.roi_canvas, self.sx, self.sy)
            if alert_triggered:
                print("Motion alert triggered by monitor.")
                image_path = "alert_image.jpg"
                cv2.imwrite(image_path, frame)
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                motion_subject = "3D Printer Alert: Motion Detected"
                motion_body = f"""
                <html>
                  <body>
                    <h2>3D Printer Alert: Motion Detected</h2>
                    <p>Motion was detected in the monitored ROI at {timestamp}.</p>
                    <p><img src="cid:alert_image"></p>
                  </body>
                </html>
                """
                if self.sender_email and self.sender_password and self.recipient_email:
                    try:
                        send_alert_email(
                            from_email=self.sender_email,
                            password=self.sender_password,
                            to_email=self.recipient_email,
                            subject=motion_subject,
                            body=motion_body,
                            image_path=image_path
                        )
                        print("Motion detection email sent.")
                    except Exception as e:
                        print(f"Error sending motion detection email: {e}")
                else:
                    print(
                        "Email credentials not set, cannot send motion detection email.")

            text = f"Diff: {db:.1f}% / {self.monitor.sensitivity}%"
            color = ALERT_BGR if db >= self.monitor.sensitivity else MINT_BGR
            cv2.putText(disp, text, (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

        if self.drawing:
            x0, y0 = min(self.ix, self.fx), min(self.iy, self.fy)
            x1, y1 = max(self.ix, self.fx), max(self.iy, self.fy)
            cv2.rectangle(disp, (int(x0 * self.sx), int(y0 * self.sy)),
                          (int(x1 * self.sx), int(y1 * self.sy)), (0, 255, 0), BOX_THICKNESS)
        elif self.roi_defined:
            x_c, y_c, w_c, h_c = self.roi_canvas
            x, y, rw, rh = int(x_c * self.sx), int(y_c *
                                                   self.sy), int(w_c * self.sx), int(h_c * self.sy)
            roi_color = MINT_BGR
            if self.running and hasattr(self.monitor, 'alert_state') and self.monitor.alert_state:
                roi_color = ALERT_BGR
            cv2.rectangle(disp, (x, y), (x+rw, y+rh), roi_color, BOX_THICKNESS)

        if not self.roi_defined and not self.drawing and not self.running:
            cv2.putText(disp, "Set a bounding box to start", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        disp_rgb = cv2.cvtColor(disp, cv2.COLOR_BGR2RGB)
        disp_pil = Image.fromarray(disp_rgb).resize((CANVAS_W, self.CANVAS_H))
        try:
            self.photo = ImageTk.PhotoImage(disp_pil)
            self.canvas.image = self.photo
            self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        except RuntimeError as e:
            if "main window deleted" in str(e).lower():
                print("Tkinter main window deleted, stopping updates.")
                return
            raise

        self.root.after(30, self.update_frame)

    def __del__(self):
        if self.cap and self.cap.isOpened():
            self.cap.release()
            print("Camera released.")
        if GPIO_AVAILABLE:
            try:
                GPIO.cleanup()
                print("GPIO cleaned up.")
            except Exception as e:
                print(f"Error during GPIO cleanup in __del__: {e}")


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    try:
        root.mainloop()
    finally:
        if GPIO_AVAILABLE and 'GPIO' in locals() and GPIO is not None:
            try:
                GPIO.cleanup()
                print("GPIO cleaned up on exit.")
            except Exception as e:
                print(f"Note: Error during GPIO cleanup on exit: {e}")
        if 'app' in locals() and hasattr(app, 'cap') and app.cap and app.cap.isOpened():
            app.cap.release()
            print("Camera released on exit.")
