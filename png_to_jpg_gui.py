# png_to_jpg_gui.py
import os
import sys
import threading
import queue
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import tkinter as tk
from tkinter import ttk, filedialog, colorchooser, messagebox
import tkinter.scrolledtext as scrolledtext

from PIL import Image, ImageOps

APP_TITLE = "PNG → JPG Batch Converter"

class ConverterGUI:
    def __init__(self, root):
        self.root = root
        root.title(APP_TITLE)
        root.geometry("760x620")
        root.minsize(720, 560)

        # Variables
        self.input_dir = tk.StringVar(value="")
        self.output_dir = tk.StringVar(value="")
        self.quality = tk.IntVar(value=92)
        self.progressive = tk.BooleanVar(value=True)
        self.optimize = tk.BooleanVar(value=True)
        self.include_subfolders = tk.BooleanVar(value=True)
        self.overwrite = tk.BooleanVar(value=False)
        self.zip_after = tk.BooleanVar(value=False)
        self.bg_color = "#FFFFFF"

        self.total_files = 0
        self.converted = 0
        self.canceled = False
        self.worker_thread = None
        self.q = queue.Queue()

        self._build_ui()
        self._poll_queue()

    def _build_ui(self):
        pad = {'padx': 10, 'pady': 6}

        frm = ttk.Frame(self.root)
        frm.pack(fill='both', expand=True)

        # Input folder
        row1 = ttk.Frame(frm)
        row1.pack(fill='x', **pad)
        ttk.Label(row1, text="Input folder (PNG):").pack(side='left')
        ttk.Entry(row1, textvariable=self.input_dir).pack(side='left', fill='x', expand=True, padx=6)
        ttk.Button(row1, text="Browse…", command=self.browse_input).pack(side='left')
        self.count_lbl = ttk.Label(row1, text="")
        self.count_lbl.pack(side='left', padx=10)

        # Output folder
        row2 = ttk.Frame(frm)
        row2.pack(fill='x', **pad)
        ttk.Label(row2, text="Output folder (JPG):").pack(side='left')
        ttk.Entry(row2, textvariable=self.output_dir).pack(side='left', fill='x', expand=True, padx=6)
        ttk.Button(row2, text="Browse…", command=self.browse_output).pack(side='left')

        # Options
        opt = ttk.Labelframe(frm, text="Options")
        opt.pack(fill='x', **pad)

        # Quality slider
        qrow = ttk.Frame(opt)
        qrow.pack(fill='x', padx=10, pady=4)
        ttk.Label(qrow, text="JPEG quality:").pack(side='left')
        self.quality_scale = ttk.Scale(qrow, from_=60, to=100, orient='horizontal',
                                       command=lambda v: self.quality.set(int(float(v))))
        self.quality_scale.set(self.quality.get())
        self.quality_scale.pack(side='left', fill='x', expand=True, padx=8)
        self.quality_lbl = ttk.Label(qrow, text=str(self.quality.get()))
        self.quality_lbl.pack(side='left')
        self.quality.trace_add('write', lambda *args: self.quality_lbl.config(text=str(self.quality.get())))

        # Background color picker
        brow = ttk.Frame(opt)
        brow.pack(fill='x', padx=10, pady=4)
        ttk.Label(brow, text="Background (for transparent PNG):").pack(side='left')
        self.bg_patch = tk.Label(brow, text="  ", background=self.bg_color, relief='groove', width=4)
        self.bg_patch.pack(side='left', padx=6)
        ttk.Button(brow, text="Pick color…", command=self.pick_color).pack(side='left')

        # checkboxes
        c_row = ttk.Frame(opt)
        c_row.pack(fill='x', padx=10, pady=4)
        ttk.Checkbutton(c_row, text="Include subfolders", variable=self.include_subfolders).pack(side='left')
        ttk.Checkbutton(c_row, text="Progressive", variable=self.progressive).pack(side='left', padx=10)
        ttk.Checkbutton(c_row, text="Optimize", variable=self.optimize).pack(side='left', padx=10)
        ttk.Checkbutton(c_row, text="Overwrite if exists", variable=self.overwrite).pack(side='left', padx=10)
        ttk.Checkbutton(c_row, text="Create ZIP after convert", variable=self.zip_after).pack(side='left', padx=10)

        # Progress
        prog = ttk.Labelframe(frm, text="Progress")
        prog.pack(fill='x', **pad)
        self.pb = ttk.Progressbar(prog, mode='determinate')
        self.pb.pack(fill='x', padx=10, pady=6)
        self.status = ttk.Label(prog, text="Ready")
        self.status.pack(side='left', padx=10, pady=4)
        ttk.Button(prog, text="Open output folder", command=self.open_output).pack(side='right', padx=10, pady=4)

        # Log
        logf = ttk.Labelframe(frm, text="Log")
        logf.pack(fill='both', expand=True, **pad)
        self.log = scrolledtext.ScrolledText(logf, height=12, state='disabled')
        self.log.pack(fill='both', expand=True, padx=8, pady=6)

        # Action buttons
        ab = ttk.Frame(frm)
        ab.pack(fill='x', **pad)
        self.start_btn = ttk.Button(ab, text="Start", command=self.start)
        self.start_btn.pack(side='left')
        self.cancel_btn = ttk.Button(ab, text="Cancel", command=self.cancel, state='disabled')
        self.cancel_btn.pack(side='left', padx=6)

    def browse_input(self):
        d = filedialog.askdirectory(title="Select input folder with PNG")
        if d:
            self.input_dir.set(d)
            if not self.output_dir.get():
                self.output_dir.set(str(Path(d) / "jpg_out"))
            self.update_count()

    def browse_output(self):
        d = filedialog.askdirectory(title="Select output folder (JPG)")
        if d:
            self.output_dir.set(d)

    def pick_color(self):
        color, _ = colorchooser.askcolor(color=self.bg_color, title="Pick background color for transparency")
        if color:
            self.bg_color = '#%02x%02x%02x' % tuple(map(int, color))
            self.bg_patch.config(background=self.bg_color)

    def update_count(self):
        p = Path(self.input_dir.get())
        if not p.exists():
            self.count_lbl.config(text="")
            return
        if self.include_subfolders.get():
            files = list(p.rglob("*.png")) + list(p.rglob("*.PNG"))
        else:
            files = list(p.glob("*.png")) + list(p.glob("*.PNG"))
        self.total_files = len(files)
        self.count_lbl.config(text=f"{self.total_files} PNG found")

    def log_put(self, msg):
        self.q.put(("log", msg))

    def status_put(self, msg):
        self.q.put(("status", msg))

    def progress_set(self, value, maximum=None):
        self.q.put(("progress", (value, maximum)))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.log.configure(state='normal')
                    self.log.insert('end', payload + "\n")
                    self.log.see('end')
                    self.log.configure(state='disabled')
                elif kind == "status":
                    self.status.config(text=payload)
                elif kind == "progress":
                    value, maximum = payload
                    if maximum is not None:
                        self.pb.config(maximum=maximum)
                    self.pb.config(value=value)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def start(self):
        if self.worker_thread and self.worker_thread.is_alive():
            return
        in_dir = Path(self.input_dir.get())
        out_dir = Path(self.output_dir.get())

        if not in_dir.exists():
            messagebox.showerror("Error", "Please select a valid input folder.")
            return

        # Collect files
        if self.include_subfolders.get():
            files = [p for p in in_dir.rglob("*") if p.suffix.lower()==".png"]
        else:
            files = [p for p in in_dir.glob("*.png")]

        if not files:
            messagebox.showinfo("No files", "No PNG files found in the selected folder.")
            return

        out_dir.mkdir(parents=True, exist_ok=True)
        self.total_files = len(files)
        self.converted = 0
        self.canceled = False

        # Disable controls
        self.start_btn.config(state='disabled')
        self.cancel_btn.config(state='normal')
        self.pb.config(value=0, maximum=self.total_files)
        self.status_put(f"Converting 0/{self.total_files} …")
        self.log_put(f"Start converting {self.total_files} file(s)")
        self.worker_thread = threading.Thread(target=self.worker, args=(files, in_dir, out_dir), daemon=True)
        self.worker_thread.start()

    def cancel(self):
        if self.worker_thread and self.worker_thread.is_alive():
            self.canceled = True
            self.status_put("Canceling …")

    def worker(self, files, in_dir: Path, out_dir: Path):
        try:
            for idx, in_path in enumerate(files, start=1):
                if self.canceled:
                    self.log_put("Canceled by user.")
                    break
                try:
                    rel = in_path.relative_to(in_dir) if self.include_subfolders.get() else Path(in_path.name)
                except Exception:
                    rel = Path(in_path.name)

                out_subdir = out_dir / rel.parent
                out_subdir.mkdir(parents=True, exist_ok=True)
                out_path = out_subdir / (in_path.stem + ".jpg")
                if out_path.exists() and not self.overwrite.get():
                    # find unique name
                    i = 1
                    while True:
                        candidate = out_subdir / f"{in_path.stem}_{i}.jpg"
                        if not candidate.exists():
                            out_path = candidate
                            break
                        i += 1
                try:
                    with Image.open(in_path) as im:
                        im = ImageOps.exif_transpose(im)
                        if im.mode in ("RGBA","LA") or (im.mode=="P" and "transparency" in im.info):
                            bg = Image.new("RGB", im.size, self._parse_color(self.bg_color))
                            alpha = im.split()[-1] if im.mode != "P" else im.convert("RGBA").split()[-1]
                            bg.paste(im, mask=alpha)
                            im = bg
                        else:
                            im = im.convert("RGB")
                        im.save(out_path, "JPEG", quality=int(self.quality.get()),
                                optimize=bool(self.optimize.get()), progressive=bool(self.progressive.get()))
                    self.converted += 1
                    self.log_put(f"✓ {in_path} → {out_path}")
                except Exception as e:
                    self.log_put(f"✗ {in_path} — ERROR: {e}")

                self.progress_set(self.converted, self.total_files)
                self.status_put(f"Converting {self.converted}/{self.total_files} …")

            if not self.canceled:
                self.status_put(f"Done: {self.converted}/{self.total_files} converted.")
                self.log_put("Conversion finished.")
                if self.zip_after.get():
                    zip_path = out_dir.with_suffix(".zip")
                    self.log_put(f"Creating ZIP: {zip_path}")
                    with ZipFile(zip_path, "w", ZIP_DEFLATED) as zf:
                        for p in out_dir.rglob("*.jpg"):
                            zf.write(p, p.relative_to(out_dir))
                    self.log_put("ZIP created.")
        finally:
            # Re-enable controls
            self.q.put(("progress", (self.converted, self.total_files)))
            self.root.after(0, lambda: (self.start_btn.config(state='normal'), self.cancel_btn.config(state='disabled')))

    def _parse_color(self, hex_or_tuple):
        if isinstance(hex_or_tuple, str):
            s = hex_or_tuple.strip()
            if s.startswith("#") and len(s) in (4,7):
                if len(s) == 4:
                    # #rgb => expand
                    r = int(s[1]*2, 16)
                    g = int(s[2]*2, 16)
                    b = int(s[3]*2, 16)
                    return (r,g,b)
                return tuple(int(s[i:i+2], 16) for i in (1,3,5))
        return (255,255,255)

    def open_output(self):
        out = self.output_dir.get()
        if not out:
            return
        p = Path(out)
        if not p.exists():
            messagebox.showinfo("Info", "Output folder does not exist yet.")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(p))
            elif sys.platform == "darwin":
                os.system(f'open "{p}"')
            else:
                os.system(f'xdg-open "{p}"')
        except Exception as e:
            messagebox.showerror("Error", f"Cannot open folder: {e}")

def main():
    root = tk.Tk()
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    app = ConverterGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
