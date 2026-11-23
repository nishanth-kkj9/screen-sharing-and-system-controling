"""Small, separate Transport-layer demonstrations (Module 4). Standard library only.
They do NOT use the screen-sharing code; run them while Wireshark captures.

  python demo/transport_demos.py boundaries            TCP byte stream vs UDP datagrams (one machine)
  python demo/transport_demos.py ports                 one server port, two clients, two source ports
  python demo/transport_demos.py flow-recv [--delay S] receiver that reads slowly      (laptop B)
  python demo/transport_demos.py flow-send --host IP   sender that reports blocking    (laptop A)
"""
import argparse
import socket
import threading
import time

PORT = 6000


def boundaries():
    """Send three messages of 10, 20 and 30 bytes over UDP and over TCP; count the reads."""
    sizes = (10, 20, 30)
    # UDP: each datagram arrives as its own message
    us = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); us.bind(("127.0.0.1", 0))
    uaddr = us.getsockname(); uc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for n in sizes:
        uc.sendto(b"u" * n, uaddr)
    time.sleep(0.2); got = []
    us.settimeout(0.5)
    try:
        while True:
            got.append(len(us.recvfrom(4096)[0]))
    except socket.timeout:
        pass
    print("UDP: sent", sizes, "-> receiver read", got, "(message boundaries kept)")
    # TCP: the same three sends are just a byte stream
    ls = socket.socket(); ls.bind(("127.0.0.1", 0)); ls.listen(1)
    c = socket.create_connection(ls.getsockname()); s, _ = ls.accept()
    c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # even with Nagle off
    for n in sizes:
        c.sendall(b"t" * n)
    time.sleep(0.2); s.settimeout(0.5); got = []
    try:
        while True:
            d = s.recv(4096)
            if not d:
                break
            got.append(len(d))
    except socket.timeout:
        pass
    print("TCP: sent", sizes, "-> receiver read", got, "(total", sum(got), "bytes; TCP does not keep message boundaries, so read sizes need not match send sizes)")
    print("=> this is why the project adds a 5-byte header: type + length (protocol.py)")


def ports():
    ls = socket.socket(); ls.bind(("127.0.0.1", 0)); ls.listen(5)
    sp = ls.getsockname()[1]; conns = []
    for i in (1, 2):
        c = socket.create_connection(("127.0.0.1", sp)); s, peer = ls.accept()
        conns.append((c, s))
        print("Viewer %d: client %s -> server port %d (server sees peer %s)" % (i, c.getsockname(), sp, peer))
    print("Same server port, different client ports: the OS tells the two connections apart")
    print("by (source IP, source port, destination IP, destination port).")


def flow_recv(delay, chunk):
    ls = socket.socket(); ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ls.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8192)  # small buffer so the window fills quickly (set BEFORE listen)
    ls.bind(("0.0.0.0", PORT)); ls.listen(1); print("receiver listening on", PORT, "delay", delay)
    s, peer = ls.accept(); total = 0; t0 = time.time()
    while True:
        d = s.recv(chunk)
        if not d:
            break
        total += len(d); time.sleep(delay)
    print("receiver got %d bytes in %.1f s" % (total, time.time() - t0))


def flow_send(host, seconds, block):
    """Send as fast as the OS accepts data and print how many bytes were accepted each second."""
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8192)  # small send buffer too
    s.connect((host, PORT)); payload = b"x" * block
    t0 = time.time(); t_mark = t0; sent = 0; last = 0
    print("second | bytes accepted by TCP in that second")
    while time.time() - t0 < seconds:
        s.sendall(payload); sent += block  # blocks when the receiver's window and our buffer are full
        if time.time() - t_mark >= 1.0:
            print("%6d | %d" % (round(time.time() - t0), sent - last)); last = sent; t_mark = time.time()
    print("total %d bytes. With a slow receiver the rate follows the receiver's reading speed: TCP flow control." % sent)
    s.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("mode", choices=["boundaries", "ports", "flow-recv", "flow-send"])
    ap.add_argument("--host", default="127.0.0.1"); ap.add_argument("--delay", type=float, default=0.5)
    ap.add_argument("--chunk", type=int, default=1024); ap.add_argument("--seconds", type=float, default=10)
    ap.add_argument("--block", type=int, default=4096)
    a = ap.parse_args()
    {"boundaries": boundaries, "ports": ports,
     "flow-recv": lambda: flow_recv(a.delay, a.chunk),
     "flow-send": lambda: flow_send(a.host, a.seconds, a.block)}[a.mode]()
