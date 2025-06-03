import cv2
import numpy as np
from rembg import remove, new_session
from PIL import Image


class Monitor:
    def __init__(
        self,
        sensitivity,
        consecutive_threshold,
        blend_alpha,
        mint_bgr,
        alert_bgr,
        box_thickness,
        model_name="u2netp",           # ← default to the lighter model

        # 라즈베리파이 3 -> u2netp # Raspberry pi 3
        # 라즈베리파이 4 -> u2net # Raspberry pi 4
        # 라즈베리파이 5 ->isnet-general-use # Raspberry pi 5
        # PC - > isnet-general-use
        # 뭔지 모르겠다면 걸들지 말것
        # if you dont know what it is, dont change

        # u2net: 일반적인 객체 감지 및 배경 제거에 적합한 표준 모델입니다. (Standard model for general object detection and background removal.)

        # u2netp: u2net의 경량 버전으로, 더 빠르고 적은 메모리를 사용하지만 약간의 정확도 저하가 있을 수 있습니다. (Lightweight version of u2net, faster with less memory, potentially with slightly reduced accuracy.)

        # isnet-general-use: 일반적으로 사용되는 새로운 모델로, 향상된 성능을 제공할 수 있습니다. (A newer general-use model that may offer improved performance.)

    ):
        self.sensitivity = sensitivity
        self.consecutive_threshold = consecutive_threshold
        self.blend_alpha = blend_alpha
        self.mint_bgr = mint_bgr
        self.alert_bgr = alert_bgr
        self.box_thickness = box_thickness

        # create a single Rembg session with the light U²-Net-P model
        self.session = new_session(model_name)

        self.reset()
        self.db = 0

    def reset(self):
        self.baseline_mask = None
        self.prev_mask = None
        self.abnormal_count = 0
        self.alert = False

    def process_frame(self, frame, roi_canvas, sx, sy):
        disp = frame.copy()
        x_c, y_c, w_c, h_c = roi_canvas
        x = int(x_c * sx)
        y = int(y_c * sy)
        rw = int(w_c * sx)
        rh = int(h_c * sy)

        # Apply rembg to the entire frame using our lightweight session
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)
        out = remove(pil, session=self.session)
        outnp = np.array(out)
        alpha = outnp[:, :, 3]

        # Create mask for ROI
        mask = np.zeros_like(alpha, dtype=np.uint8)
        mask[y: y + rh, x: x + rw] = alpha[y: y + rh, x: x + rw]

        if self.baseline_mask is None:
            self.baseline_mask = mask.copy()
            self.prev_mask = mask.copy()
            self.abnormal_count = 0
            self.alert = False
            alert_triggered_this_frame = False
        else:
            total = rw * rh * 255.0
            dp = cv2.absdiff(mask, self.prev_mask).sum() / total * 100
            self.db = cv2.absdiff(mask, self.baseline_mask).sum() / total * 100
            normal = (dp < self.sensitivity and self.db < self.sensitivity)
            if normal:
                self.abnormal_count = 0
                self.baseline_mask = mask.copy()
                if self.alert:
                    self.alert = False
                alert_triggered_this_frame = False
            else:
                self.abnormal_count += 1
                if (
                    self.abnormal_count >= self.consecutive_threshold
                    and not self.alert
                ):
                    self.alert = True
                    alert_triggered_this_frame = True
                else:
                    alert_triggered_this_frame = False
            self.prev_mask = mask.copy()

        # Create overlay
        overlay = disp.copy()
        reg = overlay[y: y + rh, x: x + rw]
        green = np.zeros_like(reg)
        green[:] = self.mint_bgr
        mroi = (mask[y: y + rh, x: x + rw] > 0)
        tinted = cv2.addWeighted(
            reg, 1 - self.blend_alpha, green, self.blend_alpha, 0)
        reg[mroi] = tinted[mroi]
        overlay[y: y + rh, x: x + rw] = reg
        disp = overlay

        if self.alert:
            red = np.zeros_like(disp)
            red[:] = self.alert_bgr
            disp = cv2.addWeighted(disp, 0.5, red, 0.5, 0)

        box_col = self.alert_bgr if self.alert else self.mint_bgr
        cv2.rectangle(disp, (x, y), (x + rw, y + rh),
                      box_col, self.box_thickness)
        seq_txt = f"{self.abnormal_count}/{self.consecutive_threshold}"
        cv2.putText(
            disp,
            seq_txt,
            (x + 5, y + 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            box_col,
            2,
        )

        return disp, alert_triggered_this_frame, self.db
