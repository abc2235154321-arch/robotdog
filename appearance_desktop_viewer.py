#!/usr/bin/env python3
"""Lightweight Tk viewer of the existing local appearance preview server.

No browser, OpenCV HighGUI, ROS imports or motor-control commands.
Only the main thread touches Tk; bounded background I/O cannot freeze the UI.
"""
import argparse
import base64
import queue
import threading

from appearance_preview_client import PreviewClient

LABELS = {"red": "紅", "orange": "橘", "yellow": "黃", "green": "綠", "blue": "藍",
          "purple": "紫", "black": "黑", "white": "白", "gray": "灰"}
STATES = {"ACQUIRING": "等待匹配", "LOCKED": "已鎖定", "LOST": "目標遺失", "IDLE": "未選目標"}


def jpeg_to_png(jpeg, maximum_width, maximum_height, canvas=True):
    import cv2
    import numpy as np
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Cannot decode preview JPEG")
    # The current server has a 960x820 canvas with a 540x540 camera at x=210.
    # Crop its English footer; show readable native status separately in Tk.
    if canvas and image.shape[:2] == (820, 960):
        image = image[:540, 210:750]
    height, width = image.shape[:2]
    ratio = min(1.0, maximum_width / width, maximum_height / height)
    image = cv2.resize(image, (max(1, int(width * ratio)), max(1, int(height * ratio))))
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("Cannot encode preview PNG")
    return encoded.tobytes()


class PreviewWorker:
    def __init__(self, client, maximum_width, maximum_height, view="projected"):
        self.client = client
        self.width, self.height = maximum_width, maximum_height
        self.view = view
        self.stopped = threading.Event()
        self.commands = queue.Queue(maxsize=8)
        self.frames = queue.Queue(maxsize=1)
        self.thread = threading.Thread(target=self.run, daemon=True)

    def submit(self, request):
        try:
            self.commands.put_nowait(request)
            return True
        except queue.Full:
            return False

    def run(self):
        while not self.stopped.is_set():
            status, png, error = {}, None, None
            try:
                # At most one queued command per iteration; close stays responsive.
                try:
                    request = self.commands.get_nowait()
                except queue.Empty:
                    request = None
                if request is not None:
                    self.client.command(request)
                if self.stopped.is_set():
                    return
                status = self.client.status()
                if self.stopped.is_set():
                    return
                view = self.view
                status = dict(status, view=view)
                if view == "raw":
                    age = status.get("raw_camera_age")
                    if age is None or not -0.05 <= age <= 0.30:
                        raise RuntimeError("原始相機畫面未更新；不顯示舊畫面")
                elif status.get("frame_live") is False:
                    raise RuntimeError("校正畫面未更新；不顯示舊人物框")
                png = jpeg_to_png(self.client.jpeg(view=view), self.width, self.height, canvas=view == "projected")
            except Exception as exc:
                error = str(exc)
            try:
                self.frames.get_nowait()
            except queue.Empty:
                pass
            self.frames.put_nowait((status, png, error))
            self.stopped.wait(0.20)

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=0.2)


def main():
    import tkinter as tk
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8766")
    parser.add_argument("--view", choices=("raw", "projected"), default="raw",
                        help="Default raw shows the full original image without projection or detection boxes")
    args = parser.parse_args()
    client = PreviewClient(args.url)
    root = tk.Tk()
    root.title("Pupper 上衣顏色預覽 — 請確認服務模式")
    width = max(300, min(960, root.winfo_screenwidth() - 40))
    height = max(280, min(800, root.winfo_screenheight() - 40))
    root.geometry(f"{width}x{height}")
    root.configure(bg="#15191f")
    root.columnconfigure(0, weight=1)
    root.rowconfigure(2, weight=1)
    controls = tk.Frame(root, bg="#15191f")
    controls.grid(row=0, column=0, pady=4)
    status_label = tk.Label(root, text="正在連線到狗本機預覽…", bg="#15191f", fg="#ffce70",
                            font=("sans-serif", 10), wraplength=width - 20, justify="left")
    status_label.grid(row=1, column=0, padx=8, sticky="ew")
    image_label = tk.Label(root, bg="black")
    image_label.grid(row=2, column=0, padx=4, pady=4)
    notice_label = tk.Label(root, text="正在確認服務模式｜關閉預覽不停止後端", bg="#15191f", fg="white",
                            font=("sans-serif", 9), wraplength=width - 20)
    notice_label.grid(row=3, column=0, pady=2)
    worker = PreviewWorker(client, width - 16, max(120, height - 160), args.view)
    # Decoding/resizing works in headless OpenCV; no namedWindow/imshow calls.
    import cv2
    cv2.setNumThreads(1)
    color_controls = tk.Frame(controls, bg="#15191f")
    color_controls.pack(side="top")
    target_buttons = []
    for color, label in LABELS.items():
        button = tk.Button(color_controls, text=label, width=2, state="disabled",
                           command=lambda color=color: worker.submit({"color": color}))
        button.pack(side="left", padx=1)
        target_buttons.append(button)
    button = tk.Button(color_controls, text="重選", state="disabled", command=lambda: worker.submit({"reset": True}))
    button.pack(side="left", padx=3)
    target_buttons.append(button)
    view_controls = tk.Frame(controls, bg="#15191f")
    view_controls.pack(side="bottom")
    # Local display selection only: does not reconfigure ROS or reset the lock.
    tk.Button(view_controls, text="原始相機（完整）",
              command=lambda: setattr(worker, "view", "raw")).pack(side="left", padx=3)
    tk.Button(view_controls, text="校正畫面（人物框）",
              command=lambda: setattr(worker, "view", "projected")).pack(side="left", padx=3)
    closed = False
    photo = None
    callback_id = None

    def poll():
        nonlocal photo, callback_id
        if closed:
            return
        try:
            status, png, error = worker.frames.get_nowait()
        except queue.Empty:
            pass
        else:
            if error:
                status_label.configure(text="等待／連線錯誤：" + error)
                # Never leave the previous live-looking image on network failure.
                image_label.configure(image="")
                photo = None
                for button in target_buttons:
                    button.configure(state="disabled")
            else:
                execution = status.get("mode") == "APPEARANCE_FOLLOW"
                observation = status.get("mode") == "OBSERVATION_ONLY"
                for button in target_buttons:
                    button.configure(state="normal" if observation else "disabled")
                notice_label.configure(text=("實際控制：" + ("已武裝，依鎖定狀態運動" if status.get("active") else "跟隨停用") +
                                             "｜預覽唯讀，關閉不停止移動" if execution else
                                             "僅觀察，不控制馬達｜關閉不停止相機／分析" if observation else
                                             "未知模式｜預覽唯讀"))
                color = LABELS.get(status.get("color"), "?")
                state = STATES.get(status.get("state"), status.get("state", "等待"))
                raw_view = status.get("view") == "raw"
                camera_age = status.get("raw_camera_age" if raw_view else "camera_age")
                age = "?" if camera_age is None else f"{camera_age:.3f}"
                stale = "｜服務畫面未更新" if status.get("server_age", 0) > 1 else ""
                view_label = "原始相機：完整、無人物框" if raw_view else "校正畫面：人物框"
                status_label.configure(text=f"{view_label}{stale}｜延遲 {age} 秒\n{color}色上衣｜{state}｜校正圖人物 {status.get('people', '?')}，符合 {status.get('matches', '?')}\n{status.get('reason', '')}")
                photo = tk.PhotoImage(data=base64.b64encode(png).decode("ascii"), format="png")
                image_label.configure(image=photo)
        callback_id = root.after(50, poll)

    def close():
        nonlocal closed
        closed = True
        if callback_id is not None:
            root.after_cancel(callback_id)
        worker.close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    root.bind("<Escape>", lambda event: close())
    worker.thread.start()
    poll()
    print("TK_PREVIEW: display only; backend mode is shown on screen. Closing preview does NOT stop motion.", flush=True)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        if not closed:
            close()
    finally:
        worker.close()


if __name__ == "__main__":
    main()
