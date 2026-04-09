"""Renderização do terminal: tabela Live, console estável e status."""
from __future__ import annotations

import time
from collections import deque
from queue import Empty, Queue
from typing import TYPE_CHECKING

from rich.live import Live
from rich.table import Table

from .constants import TABLE_BOX, console
from .latency_profile import LatencyProfile
from .result import Result

if TYPE_CHECKING:
    from .pipeline import AudioPipeline


def build_table(
    results:    deque,
    target_lang: str,
    status:     str,
    partials:   "dict[str, Result] | None" = None,
) -> Table:
    table = Table(
        title=(
            f"[bold cyan]Tradutor em Tempo Real[/bold cyan]"
            f"  ->  [bold green]{target_lang.upper()}[/bold green]"
            f"  [dim]|  {status}[/dim]"
        ),
        show_header=True,
        header_style="bold white on dark_blue",
        border_style="bright_blue",
        box=TABLE_BOX,
        expand=True,
        show_lines=False,
        padding=(0, 1),
    )
    table.add_column("Hora",             style="dim",       width=10, justify="center")
    table.add_column("Fonte",            style="bold cyan", width=13, justify="center")
    table.add_column("Idioma detectado", style="yellow",    width=18, justify="center")
    table.add_column("Original",         style="white",     ratio=2)
    table.add_column(f"-> {target_lang.upper()}", style="bold green", ratio=2)
    table.add_column("Latencia",         style="magenta",   width=10, justify="right")

    for r in (partials or {}).values():
        table.add_row(
            r.ts, f"{r.source}*", r.lang,
            f"[yellow dim]{r.original}[/yellow dim]",
            f"[green dim]{r.translation}[/green dim]",
            f"[yellow]{r.latency_ms:.0f}ms[/yellow]",
        )

    for r in results:
        lc = "green" if r.latency_ms < 500 else ("yellow" if r.latency_ms < 1500 else "red")
        table.add_row(
            r.ts, r.source, r.lang, r.original, r.translation,
            f"[{lc}]{r.latency_ms:.0f}ms[/{lc}]",
        )

    if not results:
        table.add_row("", "", "", "[dim]Aguardando fala...[/dim]", "", "")

    return table


def build_runtime_status(
    device:             str,
    model_name:         str,
    tuning:             LatencyProfile,
    sources:            list[str],
    pipelines:          "list[AudioPipeline]",
    interpretation_mode: str,
    provider_stats:     "dict[str, object] | None" = None,
) -> str:
    parts = [f"{device.upper()} {model_name}", f"profile={tuning.name}", f"mode={interpretation_mode}"]
    parts.extend(sources)

    for pipe in pipelines:
        if pipe.last_latency_ms <= 0:
            continue

        cache_label = "cache" if pipe.last_cache_hit else pipe.last_provider

        # Idioma travado
        lang_label = f" lang={pipe.locked_lang}(locked)" if pipe.locked_lang else ""

        # Métricas de latência parcial e fila (só exibe se relevantes)
        partial_label = (
            f" partial={pipe.last_first_partial_ms:.0f}ms"
            if pipe.last_first_partial_ms > 0 else ""
        )
        qwait_label = (
            f" qwait={pipe.last_queue_wait_ms:.0f}ms"
            if pipe.last_queue_wait_ms > 10 else ""
        )

        # Drop e fallback rates (só exibe se acima de threshold de ruído)
        drop_label = (
            f" drop={pipe.drop_rate:.1%}"
            if pipe.drop_rate > 0.005 else ""
        )
        fallback_label = (
            f" fallback={pipe.fallback_rate:.0%}"
            if pipe.fallback_rate > 0.05 else ""
        )

        # Context cooldown
        remaining = max(0.0, getattr(pipe, "_context_cooldown_until", 0.0) - time.perf_counter())
        ctx_label = f" ctx-pause={remaining:.0f}s" if remaining > 0 else ""

        parts.append(
            f"{pipe.label}:asr={pipe.last_transcribe_ms:.0f}ms"
            f" tr={pipe.last_translate_ms:.0f}ms {cache_label}"
            f"{lang_label}{partial_label}{qwait_label}{drop_label}{fallback_label}{ctx_label}"
        )

    # ── Indicadores de saúde ──
    health_parts = _build_health_indicators(device, pipelines, provider_stats)
    if health_parts:
        parts.append(health_parts)

    return " | ".join(parts)


def _build_health_indicators(
    device: str,
    pipelines: "list[AudioPipeline]",
    provider_stats: "dict[str, object] | None",
) -> str:
    """Gera uma string compacta de indicadores de saúde do sistema."""
    indicators = []

    # GPU
    gpu_ok = device.lower() == "cuda"
    indicators.append(f"GPU:{'OK' if gpu_ok else 'CPU'}")

    # Drop rate agregado
    total_fed = sum(getattr(p, "_total_chunks_fed", 0) for p in pipelines)
    total_drop = sum(getattr(p, "_dropped_chunks", 0) for p in pipelines)
    if total_fed > 0:
        drop_pct = total_drop / total_fed
        if drop_pct > 0.05:
            indicators.append(f"[red]DROPS:{drop_pct:.0%}[/red]")
        elif drop_pct > 0.01:
            indicators.append(f"[yellow]drops:{drop_pct:.1%}[/yellow]")

    # Provider health (circuit breakers)
    if provider_stats:
        for name, stats in provider_stats.items():
            if hasattr(stats, "is_open") and stats.is_open:
                cd = getattr(stats, "cooldown_remaining_s", 0)
                indicators.append(f"[red]{name}:OPEN({cd:.0f}s)[/red]")
            elif hasattr(stats, "consecutive_failures") and stats.consecutive_failures > 0:
                indicators.append(f"[yellow]{name}:{stats.consecutive_failures}err[/yellow]")

    if len(indicators) <= 1:
        return ""
    return "[" + " ".join(indicators) + "]"


def render_result_line(result: Result) -> tuple[str, str]:
    suffix         = " [parcial]" if result.is_partial else ""
    provider_label = f" {result.provider}" if result.provider else ""
    meta = (
        f"[{result.ts}] {result.source} {result.lang.upper()} {result.latency_ms:.0f}ms"
        f" (asr {result.transcribe_ms:.0f} / tr {result.translate_ms:.0f}){provider_label}{suffix}"
    )
    return meta, f"  {result.original}\n  -> {result.translation}"


def run_stable_console(
    results_queue:   "Queue[Result]",
    target_lang:     str,
    initial_status:  str,
    status_supplier,
) -> None:
    console.rule(
        f"[bold cyan]Tradutor Estavel[/bold cyan] -> [bold green]{target_lang.upper()}[/bold green]"
    )
    console.print(f"[dim]{initial_status}[/dim]")
    console.print("[dim]Ctrl+C para parar[/dim]\n")

    last_status    = initial_status
    last_status_at = time.perf_counter()

    while True:
        try:
            result = results_queue.get(timeout=0.2)
            current_status = status_supplier()
            if current_status != last_status:
                console.print(f"\n[dim]{current_status}[/dim]")
                last_status    = current_status
                last_status_at = time.perf_counter()
            meta, body = render_result_line(result)
            style = "yellow" if result.is_partial else "bold cyan"
            console.print(f"[{style}]{meta}[/{style}]")
            console.print(body)
            console.print()
        except Empty:
            current_status = status_supplier()
            now = time.perf_counter()
            if current_status != last_status and now - last_status_at >= 1.5:
                console.print(f"[dim]{current_status}[/dim]\n")
                last_status    = current_status
                last_status_at = now


def run_live_console(
    results:       deque,
    results_lock:  object,
    runtime_state: dict,
    target_lang:   str,
    status_str:    str,
    current_status,
) -> None:
    with Live(
        build_table(results, target_lang, status_str, runtime_state.get("partials")),
        refresh_per_second=4,
        auto_refresh=False,
        console=console,
    ) as live:
        last_version = runtime_state["results_version"]
        last_status  = status_str

        while True:
            time.sleep(0.08)
            status_str      = current_status()
            current_version = runtime_state["results_version"]
            if current_version != last_version or status_str != last_status:
                with results_lock:
                    live.update(
                        build_table(
                            results,
                            target_lang,
                            status_str,
                            dict(runtime_state.get("partials", {})),
                        ),
                        refresh=True,
                    )
                last_version = current_version
                last_status  = status_str
