"""Overlay flutuante de tradução — janela transparente sempre visível.

Exibe traduções em tempo real sobre qualquer janela ativa, sem depender
do terminal. Suporta arrastar, toggle de visibilidade e redimensionamento.

Requisitos: tkinter (incluso no Python padrão).

Uso:
    from rtxlator.overlay import TranslationOverlay

    overlay = TranslationOverlay()
    overlay.start()
    # ... em qualquer thread:
    overlay.push_result(result)
    # ... para encerrar:
    overlay.stop()
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .result import Result


@dataclass(frozen=True)
class OverlayConfig:
    """Configuração visual do overlay."""
    width: int = 600
    height: int = 200
    opacity: float = 0.88
    bg_color: str = "#1a1a2e"
    text_color: str = "#e0e0e0"
    accent_color: str = "#00d4ff"
    partial_color: str = "#888888"
    font_family: str = "Segoe UI"
    font_size: int = 12
    max_lines: int = 6
    position: str = "bottom-right"  # bottom-right, bottom-left, top-right, top-left
    margin: int = 20


class TranslationOverlay:
    """Janela overlay transparente para exibir traduções em tempo real.

    A janela roda em sua própria thread com mainloop do tkinter.
    Thread-safe: push_result() pode ser chamado de qualquer thread.
    """

    def __init__(self, config: OverlayConfig | None = None):
        self.config = config or OverlayConfig()
        self._queue: queue.Queue[Result | None] = queue.Queue(maxsize=64)
        self._thread: threading.Thread | None = None
        self._running = False
        self._root: tk.Tk | None = None
        self._lines: list[dict] = []
        self._visible = True

    def start(self) -> None:
        """Inicia a janela overlay em uma thread dedicada."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run_mainloop,
            daemon=True,
            name="overlay-ui",
        )
        self._thread.start()

    def stop(self) -> None:
        """Encerra a janela overlay."""
        self._running = False
        self._queue.put(None)
        if self._root:
            try:
                self._root.after(0, self._root.destroy)
            except Exception:
                pass

    def push_result(self, result: "Result") -> None:
        """Envia um resultado para ser exibido (thread-safe)."""
        try:
            self._queue.put_nowait(result)
        except queue.Full:
            pass

    def toggle_visibility(self) -> None:
        """Alterna visibilidade da janela."""
        self._visible = not self._visible
        if self._root:
            try:
                if self._visible:
                    self._root.after(0, self._root.deiconify)
                else:
                    self._root.after(0, self._root.withdraw)
            except Exception:
                pass

    # ── Mainloop ───────────────────────────────────────────────────────────

    def _run_mainloop(self) -> None:
        """Cria e executa a janela tk (roda na thread dedicada)."""
        cfg = self.config
        root = tk.Tk()
        self._root = root

        root.title("PX Tradutor — Overlay")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", cfg.opacity)
        root.configure(bg=cfg.bg_color)

        # Posicionamento
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        x, y = self._calc_position(screen_w, screen_h, cfg)
        root.geometry(f"{cfg.width}x{cfg.height}+{x}+{y}")

        # Frame principal com borda arredondada simulada
        main_frame = tk.Frame(root, bg=cfg.bg_color, padx=12, pady=8)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Header com título e botão fechar
        header = tk.Frame(main_frame, bg=cfg.bg_color)
        header.pack(fill=tk.X)

        title_label = tk.Label(
            header,
            text="⚡ PX Tradutor",
            font=(cfg.font_family, 9, "bold"),
            fg=cfg.accent_color,
            bg=cfg.bg_color,
        )
        title_label.pack(side=tk.LEFT)

        # Status label
        self._status_label = tk.Label(
            header,
            text="● ATIVO",
            font=(cfg.font_family, 8),
            fg="#00ff88",
            bg=cfg.bg_color,
        )
        self._status_label.pack(side=tk.LEFT, padx=(10, 0))

        close_btn = tk.Label(
            header,
            text="✕",
            font=(cfg.font_family, 10),
            fg="#666666",
            bg=cfg.bg_color,
            cursor="hand2",
        )
        close_btn.pack(side=tk.RIGHT)
        close_btn.bind("<Button-1>", lambda _: self.stop())

        minimize_btn = tk.Label(
            header,
            text="—",
            font=(cfg.font_family, 10),
            fg="#666666",
            bg=cfg.bg_color,
            cursor="hand2",
        )
        minimize_btn.pack(side=tk.RIGHT, padx=(0, 8))
        minimize_btn.bind("<Button-1>", lambda _: self.toggle_visibility())

        # Separador
        sep = tk.Frame(main_frame, bg=cfg.accent_color, height=1)
        sep.pack(fill=tk.X, pady=(4, 6))

        # Área de texto
        self._text_frame = tk.Frame(main_frame, bg=cfg.bg_color)
        self._text_frame.pack(fill=tk.BOTH, expand=True)

        self._text_labels: list[tk.Label] = []
        for _ in range(cfg.max_lines):
            lbl = tk.Label(
                self._text_frame,
                text="",
                font=(cfg.font_family, cfg.font_size),
                fg=cfg.text_color,
                bg=cfg.bg_color,
                anchor="w",
                justify=tk.LEFT,
                wraplength=cfg.width - 30,
            )
            lbl.pack(fill=tk.X, anchor="w")
            self._text_labels.append(lbl)

        # Placeholder
        self._text_labels[0].configure(text="Aguardando tradução...", fg="#555555")

        # Drag support
        self._drag_data = {"x": 0, "y": 0}
        header.bind("<ButtonPress-1>", self._on_drag_start)
        header.bind("<B1-Motion>", self._on_drag_motion)
        title_label.bind("<ButtonPress-1>", self._on_drag_start)
        title_label.bind("<B1-Motion>", self._on_drag_motion)

        # Poll de resultados
        self._poll_queue()
        root.mainloop()

    def _poll_queue(self) -> None:
        """Verifica resultados pendentes e atualiza a UI."""
        if not self._running or not self._root:
            return
        try:
            while True:
                result = self._queue.get_nowait()
                if result is None:
                    self._root.destroy()
                    return
                self._add_line(result)
        except queue.Empty:
            pass
        except tk.TclError:
            return
        try:
            self._root.after(80, self._poll_queue)
        except tk.TclError:
            pass

    def _add_line(self, result: "Result") -> None:
        """Adiciona uma linha de tradução ao overlay."""
        cfg = self.config

        entry = {
            "original": result.original[:80],
            "translated": result.translation[:80],
            "is_partial": result.is_partial,
            "provider": result.provider,
            "latency_ms": result.latency_ms,
        }

        if result.is_partial:
            # Parciais atualizam a última linha se for do mesmo source
            if self._lines and self._lines[-1].get("is_partial"):
                self._lines[-1] = entry
            else:
                self._lines.append(entry)
        else:
            # Finais removem o último parcial e adicionam
            if self._lines and self._lines[-1].get("is_partial"):
                self._lines[-1] = entry
            else:
                self._lines.append(entry)

        # Manter máximo de linhas
        max_display = cfg.max_lines // 2  # cada resultado usa 2 linhas
        if len(self._lines) > max_display:
            self._lines = self._lines[-max_display:]

        self._render_lines()

    def _render_lines(self) -> None:
        """Atualiza os labels da UI com as linhas atuais."""
        cfg = self.config

        # Limpar
        for lbl in self._text_labels:
            lbl.configure(text="", fg=cfg.text_color)

        # Renderizar
        idx = 0
        for line in self._lines:
            if idx >= len(self._text_labels) - 1:
                break

            is_partial = line.get("is_partial", False)
            provider = line.get("provider", "")
            latency = line.get("latency_ms", 0)

            # Linha original
            prefix = "⋯" if is_partial else "●"
            orig_color = cfg.partial_color if is_partial else "#aaaaaa"
            self._text_labels[idx].configure(
                text=f"  {prefix} {line['original']}",
                fg=orig_color,
                font=(cfg.font_family, cfg.font_size - 1),
            )
            idx += 1

            # Linha tradução
            latency_tag = f"  [{latency:.0f}ms {provider}]" if not is_partial else ""
            tr_color = cfg.partial_color if is_partial else cfg.accent_color
            self._text_labels[idx].configure(
                text=f"  → {line['translated']}{latency_tag}",
                fg=tr_color,
                font=(cfg.font_family, cfg.font_size, "bold" if not is_partial else "normal"),
            )
            idx += 1

    def _calc_position(self, screen_w: int, screen_h: int, cfg: OverlayConfig) -> tuple[int, int]:
        """Calcula a posição inicial da janela."""
        m = cfg.margin
        positions = {
            "bottom-right": (screen_w - cfg.width - m, screen_h - cfg.height - m - 50),
            "bottom-left":  (m, screen_h - cfg.height - m - 50),
            "top-right":    (screen_w - cfg.width - m, m),
            "top-left":     (m, m),
        }
        return positions.get(cfg.position, positions["bottom-right"])

    def _on_drag_start(self, event: tk.Event) -> None:
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

    def _on_drag_motion(self, event: tk.Event) -> None:
        if self._root:
            x = self._root.winfo_x() + event.x - self._drag_data["x"]
            y = self._root.winfo_y() + event.y - self._drag_data["y"]
            self._root.geometry(f"+{x}+{y}")
