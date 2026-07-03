
import cv2

from find_the_card import Config, Emulator

cfg = Config()
img = Emulator(cfg).screenshot()
print(f"Screen size: {img.shape[1]} x {img.shape[0]} (w x h)")
print("Click TOP-LEFT then BOTTOM-RIGHT of an area. r = reset, q = quit.")

clicks = []
view = img.copy()


def on_mouse(event, x, y, flags, param):
    global view
    if event == cv2.EVENT_MOUSEMOVE:
        cv2.setWindowTitle("calibrate", f"x={x}  y={y}")
        return
    if event != cv2.EVENT_LBUTTONDOWN:
        return

    clicks.append((x, y))
    cv2.circle(view, (x, y), 4, (0, 0, 255), -1)

    if len(clicks) == 2:
        (x0, y0), (x1, y1) = clicks
        rect = (min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
        print(f"region = {rect}   # (x, y, w, h)")
        cv2.rectangle(view, (rect[0], rect[1]),
                      (rect[0] + rect[2], rect[1] + rect[3]), (0, 0, 255), 2)
        clicks.clear()


cv2.namedWindow("calibrate", cv2.WINDOW_NORMAL)
cv2.setMouseCallback("calibrate", on_mouse)
while True:
    cv2.imshow("calibrate", view)
    key = cv2.waitKey(20) & 0xFF
    if key == ord("q"):
        break
    if key == ord("r"):
        clicks.clear()
        view = img.copy()
        print("reset")
cv2.destroyAllWindows()
