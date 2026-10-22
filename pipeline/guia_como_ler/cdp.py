"""Cliente mínimo do Chrome DevTools Protocol, só com a biblioteca padrão.
Uso como módulo: with Navegador() as nav: nav.abrir(url, largura, altura, escuro=False); nav.js("..."); nav.foto(arq, clip=None)
"""
import base64, json, os, shutil, socket, subprocess, tempfile, time, urllib.request

DIR = os.path.dirname(os.path.abspath(__file__))
PORTA_SITE = open(os.path.join(DIR, "port")).read().strip()
BASE = f"http://localhost:{PORTA_SITE}/"


class WS:
    def __init__(self, url):
        assert url.startswith("ws://")
        hostport, path = url[5:].split("/", 1)
        host, port = hostport.split(":")
        self.s = socket.create_connection((host, int(port)))
        key = base64.b64encode(os.urandom(16)).decode()
        req = f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        self.s.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.s.recv(4096)
        self.resto = buf.split(b"\r\n\r\n", 1)[1]

    def _ler(self, n):
        while len(self.resto) < n:
            d = self.s.recv(1 << 20)
            if not d:
                raise EOFError
            self.resto += d
        out, self.resto = self.resto[:n], self.resto[n:]
        return out

    def enviar(self, txt):
        data = txt.encode()
        cab = bytearray([0x81])
        n = len(data)
        if n < 126:
            cab.append(0x80 | n)
        elif n < 65536:
            cab.append(0x80 | 126); cab += n.to_bytes(2, "big")
        else:
            cab.append(0x80 | 127); cab += n.to_bytes(8, "big")
        mask = os.urandom(4)
        cab += mask
        self.s.sendall(bytes(cab) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def receber(self):
        msg = b""
        while True:
            b0, b1 = self._ler(2)
            n = b1 & 0x7F
            if n == 126:
                n = int.from_bytes(self._ler(2), "big")
            elif n == 127:
                n = int.from_bytes(self._ler(8), "big")
            if b1 & 0x80:
                self._ler(4)
            msg += self._ler(n)
            if b0 & 0x80:
                return msg.decode()


class Navegador:
    def __enter__(self):
        self.ud = tempfile.mkdtemp(dir=DIR, prefix="cdp-")
        self.p = subprocess.Popen(["google-chrome", "--headless=new", "--disable-gpu", "--hide-scrollbars", "--remote-debugging-port=0",
                                   f"--user-data-dir={self.ud}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        arq = os.path.join(self.ud, "DevToolsActivePort")
        for _ in range(100):
            if os.path.exists(arq) and open(arq).read().strip():
                break
            time.sleep(0.1)
        porta = open(arq).read().split()[0]
        for _ in range(50):
            try:
                lst = json.load(urllib.request.urlopen(f"http://127.0.0.1:{porta}/json/list"))
                pg = [x for x in lst if x["type"] == "page"][0]
                break
            except Exception:
                time.sleep(0.1)
        self.ws = WS(pg["webSocketDebuggerUrl"])
        self.i = 0
        self.cmd("Page.enable"); self.cmd("Runtime.enable")
        return self

    def __exit__(self, *a):
        try:
            self.p.terminate(); self.p.wait(5)
        except Exception:
            self.p.kill()
        shutil.rmtree(self.ud, ignore_errors=True)

    def cmd(self, metodo, **params):
        self.i += 1
        meu = self.i
        self.ws.enviar(json.dumps({"id": meu, "method": metodo, "params": params}))
        while True:
            m = json.loads(self.ws.receber())
            if m.get("id") == meu:
                if "error" in m:
                    raise RuntimeError(f"{metodo}: {m['error']}")
                return m.get("result", {})

    def abrir(self, caminho, largura=1280, altura=900, escuro=False, escala=1, espera=2.5, movel=None):
        movel = largura < 700 if movel is None else movel
        self.cmd("Emulation.setDeviceMetricsOverride", width=largura, height=altura, deviceScaleFactor=escala, mobile=movel)
        self.cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark" if escuro else "light"}])
        self.cmd("Page.navigate", url=BASE + caminho)
        time.sleep(espera)
        self.js("document.fonts.ready.then(()=>1)")
        time.sleep(0.3)

    def js(self, expr):
        r = self.cmd("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in r:
            raise RuntimeError(json.dumps(r["exceptionDetails"])[:800])
        return r["result"].get("value")

    def foto(self, arq, clip=None, pagina_toda=False):
        params = {"format": "png"}
        if pagina_toda:
            w, h = self.js("[document.documentElement.scrollWidth, document.documentElement.scrollHeight]")
            clip = {"x": 0, "y": 0, "width": w, "height": h}
        if clip:
            params["clip"] = dict(clip, scale=clip.get("scale", 1))
            params["captureBeyondViewport"] = True
        r = self.cmd("Page.captureScreenshot", **params)
        caminho = arq if os.path.isabs(arq) else os.path.join(DIR, arq)
        open(caminho, "wb").write(base64.b64decode(r["data"]))
        return caminho

    def ret(self, seletor):
        """retângulo do elemento em coordenadas da página"""
        return self.js(f"(()=>{{const r=document.querySelector({json.dumps(seletor)}).getBoundingClientRect();return {{x:r.left+scrollX,y:r.top+scrollY,width:r.width,height:r.height}}}})()")
