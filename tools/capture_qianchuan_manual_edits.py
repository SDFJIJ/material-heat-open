import json
import pathlib
import threading
import time
import urllib.request
from datetime import datetime

import websocket

CDP = "http://127.0.0.1:9223"
OUT_DIR = pathlib.Path(r"C:\Users\fmy\qcqianchuan\captures")
OUT_DIR.mkdir(parents=True, exist_ok=True)
TS = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_JSONL = OUT_DIR / f"manual_edit_network_{TS}.jsonl"
OUT_SUMMARY = OUT_DIR / "manual_edit_network_latest_summary.txt"

KEYWORDS = [
    "update-uni-prom-assist-task",
    "set_material_heat_task",
    "set_roi2_raise",
    "set_roi2_budget_slow",
    "material/set-opt",
    "batch_update_operation",
    "create-uni-prom-assist-task",
    "uni-promotion/ad/",
    "uni_promotion/",
    "material_heat",
]

file_lock = threading.Lock()
print_lock = threading.Lock()
all_captures = []
stop_event = threading.Event()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def cdp_get(path):
    with urllib.request.urlopen(CDP + path, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def qianchuan_targets():
    tabs = cdp_get("/json/list")
    targets = [
        t for t in tabs
        if t.get("type") == "page" and "qianchuan.jinritemai.com" in (t.get("url") or "") and t.get("webSocketDebuggerUrl")
    ]
    return targets


def interesting(url):
    return "qianchuan.jinritemai.com" in url and any(k in url for k in KEYWORDS)


def redact_headers(headers):
    return {
        k: ("[REDACTED]" if k.lower() in ("cookie", "x-csrftoken", "authorization") else v)
        for k, v in (headers or {}).items()
    }


def write_event(event):
    with file_lock:
        all_captures.append(event)
        with OUT_JSONL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")


def log(text):
    with print_lock:
        print(text, flush=True)


class TargetCapture:
    def __init__(self, target, index):
        self.target = target
        self.index = index
        self.ws = None
        self.msg_id = 0
        self.pending = {}
        self.reqs = {}
        self.lock = threading.Lock()

    def send(self, method, params=None):
        with self.lock:
            self.msg_id += 1
            mid = self.msg_id
            self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
            return mid

    def get_response_body(self, request_id):
        mid = self.send("Network.getResponseBody", {"requestId": request_id})
        deadline = time.time() + 2.5
        while time.time() < deadline:
            item = self.pending.pop(mid, None)
            if item is not None:
                if "result" in item:
                    body = item["result"].get("body", "")
                    if item["result"].get("base64Encoded"):
                        return "[base64 body omitted]"
                    return body[:5000]
                return json.dumps(item, ensure_ascii=False)[:1500]
            time.sleep(0.02)
        return "[body timeout]"

    def run(self):
        url = self.target.get("url") or ""
        label = f"tab{self.index}"
        try:
            self.ws = websocket.create_connection(self.target["webSocketDebuggerUrl"], timeout=1, suppress_origin=True)
            self.send("Network.enable", {"maxTotalBufferSize": 20000000, "maxResourceBufferSize": 5000000})
            self.send("Runtime.enable")
            log(f"ATTACHED {label} {url}")
            while not stop_event.is_set():
                try:
                    raw = self.ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                except Exception as e:
                    log(f"DETACHED {label} {type(e).__name__}: {e}")
                    return
                msg = json.loads(raw)
                if "id" in msg:
                    self.pending[msg["id"]] = msg
                    continue
                method = msg.get("method")
                params = msg.get("params") or {}
                if method == "Network.requestWillBeSent":
                    req = params.get("request") or {}
                    req_url = req.get("url", "")
                    if interesting(req_url):
                        rid = params.get("requestId")
                        ev = {
                            "ts": now(),
                            "target_label": label,
                            "target_url": url,
                            "kind": "request",
                            "requestId": rid,
                            "method": req.get("method"),
                            "url": req_url,
                            "postData": req.get("postData"),
                            "headers": redact_headers(req.get("headers")),
                        }
                        self.reqs[rid] = ev
                        write_event(ev)
                        log(f"CAPTURE {label} request {req.get('method')} {req_url}")
                elif method == "Network.responseReceived":
                    resp = params.get("response") or {}
                    resp_url = resp.get("url", "")
                    rid = params.get("requestId")
                    if interesting(resp_url):
                        ev = {
                            "ts": now(),
                            "target_label": label,
                            "target_url": url,
                            "kind": "response",
                            "requestId": rid,
                            "status": resp.get("status"),
                            "url": resp_url,
                            "mimeType": resp.get("mimeType"),
                        }
                        write_event(ev)
                        log(f"CAPTURE {label} response {resp.get('status')} {resp_url}")
                elif method == "Network.loadingFinished":
                    rid = params.get("requestId")
                    if rid in self.reqs:
                        body = self.get_response_body(rid)
                        ev = {"ts": now(), "target_label": label, "target_url": url, "kind": "body", "requestId": rid, "body": body}
                        write_event(ev)
                        log(f"CAPTURE {label} body requestId={rid} len={len(body)}")
        except Exception as e:
            log(f"ERROR {label} {type(e).__name__}: {e}")
        finally:
            try:
                if self.ws:
                    self.ws.close()
            except Exception:
                pass


def write_summary(targets):
    with file_lock:
        captures = list(all_captures)
    lines = [
        f"capture_file={OUT_JSONL}",
        f"targets={len(targets)}",
        f"events={len(captures)}",
        "",
    ]
    for i, t in enumerate(targets, 1):
        lines.append(f"TARGET tab{i}: {t.get('url')}")
    lines.append("")
    for ev in captures:
        if ev.get("kind") == "request":
            lines.append(f"REQUEST {ev.get('target_label')} {ev.get('method')} {ev.get('url')}")
            if ev.get("postData"):
                lines.append(f"  postData={ev.get('postData')[:1500]}")
        elif ev.get("kind") == "response":
            lines.append(f"RESPONSE {ev.get('target_label')} {ev.get('status')} {ev.get('url')}")
        elif ev.get("kind") == "body":
            lines.append(f"BODY {ev.get('target_label')} requestId={ev.get('requestId')} {ev.get('body')[:1500]}")
    OUT_SUMMARY.write_text("\n".join(lines), encoding="utf-8")
    log(f"SUMMARY {OUT_SUMMARY}")


def main():
    targets = qianchuan_targets()
    if not targets:
        print(json.dumps({"ok": False, "error": "no qianchuan tabs on CDP 9223"}, ensure_ascii=False), flush=True)
        raise SystemExit(2)
    print("READY qianchuan ALL-TAB manual edit capture", flush=True)
    print(f"out={OUT_JSONL}", flush=True)
    for i, t in enumerate(targets, 1):
        print(f"target{i}={t.get('url')}", flush=True)
    print("Now manually change budget once and ROI once; tell Hermes '改完了' when done.", flush=True)

    threads = []
    for i, t in enumerate(targets, 1):
        cap = TargetCapture(t, i)
        th = threading.Thread(target=cap.run, daemon=True)
        threads.append(th)
        th.start()
    try:
        while any(th.is_alive() for th in threads):
            time.sleep(0.5)
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        write_summary(targets)


if __name__ == "__main__":
    main()
