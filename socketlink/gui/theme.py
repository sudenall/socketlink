"""Shared look & feel for BOTH windows, so the two GUIs look like one product.

OWNER: İlayda (changes need Tina's approval too)
RULE: No colour, font or padding literals in client_gui.py / server_gui.py.
      Import them from here.
"""

FONT_FAMILY = "Segoe UI"        # Tk falls back automatically on macOS/Linux
FONT_NORMAL = (FONT_FAMILY, 10)
FONT_BOLD = (FONT_FAMILY, 10, "bold")
FONT_TITLE = (FONT_FAMILY, 13, "bold")
FONT_MONO = ("Consolas", 9)     # packet log

PAD = 8          # outer padding
PAD_SMALL = 4    # between related widgets

COLOR_BG = "#f5f6f8"
COLOR_PANEL = "#ffffff"
COLOR_TEXT = "#1f2328"
COLOR_MUTED = "#6b7280"
COLOR_ACCENT = "#2563eb"

# Connection state colours (status dot / label)
COLOR_CONNECTED = "#16a34a"
COLOR_CONNECTING = "#d97706"
COLOR_DISCONNECTED = "#dc2626"

# Packet log row colours
COLOR_PKT_SENT = "#2563eb"
COLOR_PKT_RECEIVED = "#16a34a"
COLOR_PKT_DROPPED = "#dc2626"
COLOR_PKT_RETRANSMITTED = "#d97706"

CLIENT_WINDOW_SIZE = "900x600"
SERVER_WINDOW_SIZE = "1000x650"
