#!/usr/bin/env python3
"""
Tradutor de Áudio em Tempo Real — RTX 5060 Ti + RedDragon
==========================================================
  • Captura MICROFONE (entrada) e SAÍDA DO SISTEMA (loopback WASAPI)
  • Transcreve com faster-whisper na GPU (RTX 5060 Ti, int8_float16)
  • Traduz localmente com Argos Translate; fallback Google Translate
  • Detecta automaticamente dispositivo RedDragon

Uso:
    python realtime_translator.py
    python realtime_translator.py --target en
    python realtime_translator.py --model small --source pt --target en
    python realtime_translator.py --list-devices
    python realtime_translator.py --mic-id 3 --spk-id 7
"""
from __future__ import annotations

# ── DLL preload deve ser o PRIMEIRO passo — antes de qualquer import pesado ──
from rtxlator.cuda_setup import preload_nvidia_dlls
preload_nvidia_dlls()

import argparse
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from typing import TYPE_CHECKING

import numpy as np
import pyaudiowpatch as pyaudio

from rtxlator import (
    CONTEXT_PATH,
    DEFAULT_PROFILE,
    LATENCY_PROFILES,
    MODELS_DIR,
    ensure_runtime_dirs,
    WHISPER_SR,
    AudioPipeline,
    GPUTranslator,
    OpusMTTranslator,
    PersonalLanguageContext,
    Result,
    TextProcessor,
    TranslationCache,
    build_runtime_status,
    build_table,
    console,
    detect_device,
    find_redragon_devices,
    list_all_devices,
    normalize_lang_choice,
    resolve_latency_profile,
    run_live_console,
    run_stable_console,
    select_loopback_info,
    select_mic_info,
    setup_loopback,
    setup_mic,
)
# Re-exports para compatibilidade com testes e scripts externos
from rtxlator.constants import extract_contextual_segment
from rtxlator.latency_profile import LatencyProfile
from rtxlator.text_processing import make_translation_cache_key
from rtxlator.display import render_result_line
from rtxlator.overlay import TranslationOverlay, OverlayConfig
from rtxlator.pipeline_bridge import runtime_status_summary

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ─── ASR ──────────────────────────────────────────────────────────────────────

def load_whisper_model(model_name: str, device: str, compute_type: str) -> "WhisperModel":
    from faster_whisper import WhisperModel
    return WhisperModel(model_name, device=device, compute_type=compute_type, num_workers=4)


def warm_up_models(models: "list[WhisperModel]", source_lang: str | None, tuning) -> None:
    sample = np.zeros(int(max(tuning.buffer_min_s, 0.3) * WHISPER_SR), dtype=np.float32)
    for model in models:
        try:
            segments_gen, _ = model.transcribe(
                sample,
                beam_size=1, best_of=1,
                language=source_lang,
                condition_on_previous_text=False,
                without_timestamps=tuning.without_timestamps,
                vad_filter=False,
                temperature=0,
            )
            list(segments_gen)
        except Exception:
            pass


# ─── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    ensure_runtime_dirs()

    ap = argparse.ArgumentParser(
        description="Tradutor de audio em tempo real (RTX 5060 Ti + RedDragon)"
    )
    ap.add_argument("--model",    default="base",
                    choices=["tiny", "base", "small", "medium", "large-v3"],
                    help="Modelo Whisper (padrao: base)")
    ap.add_argument("--source",   default=None,
                    help="Idioma de origem — ex: en, pt, es (padrao: auto-detect)")
    ap.add_argument("--target",   default="pt",
                    help="Idioma de destino (padrao: pt)")
    ap.add_argument("--device",   default=None, choices=["cpu", "cuda"],
                    help="Forcar device (padrao: auto-detect)")
    ap.add_argument("--mic-id",   type=int, default=None,
                    help="Forcar ID do microfone")
    ap.add_argument("--spk-id",   type=int, default=None,
                    help="Forcar ID do loopback do speaker")
    ap.add_argument("--list-devices", action="store_true",
                    help="Listar dispositivos de audio e sair")
    ap.add_argument("--no-mic",   action="store_true",  help="Desativar microfone")
    ap.add_argument("--no-spk",   action="store_true",  help="Desativar saida do sistema")
    ap.add_argument("--latency-profile", default=DEFAULT_PROFILE,
                    choices=sorted(LATENCY_PROFILES.keys()),
                    help=f"Perfil de latencia (padrao: {DEFAULT_PROFILE})")
    ap.add_argument("--ui-mode",  default="auto", choices=["auto", "live", "stable"],
                    help="Modo da interface do terminal")
    ap.add_argument("--interpretation-mode", default="hybrid",
                    choices=["fast", "hybrid", "contextual"],
                    help="Equilibrio entre traducao literal e contextual")
    ap.add_argument("--chunk-seconds",   type=float, default=None)
    ap.add_argument("--buffer-min-s",    type=float, default=None)
    ap.add_argument("--buffer-flush-s",  type=float, default=None)
    ap.add_argument("--partial-flush-s", type=float, default=None,
                    help="Intervalo de flush parcial (default: depende do perfil)")
    ap.add_argument("--silence-chunks",  type=int,   default=None)
    ap.add_argument("--distil-model", default="Systran/faster-distil-whisper-large-v3",
                    help="Modelo Distil-Whisper para perfil system_en (padrao: faster-distil-whisper-large-v3)")
    ap.add_argument("--overlay", action="store_true",
                    help="Ativar overlay flutuante de traducao (janela transparente always-on-top)")
    args = ap.parse_args()
    args.source = normalize_lang_choice(args.source)

    tuning  = resolve_latency_profile(
        args.latency_profile,
        chunk_seconds=args.chunk_seconds,
        buffer_min_s=args.buffer_min_s,
        buffer_flush_s=args.buffer_flush_s,
        partial_flush_s=args.partial_flush_s,
        silence_chunks=args.silence_chunks,
    )
    ui_mode = "stable" if args.ui_mode == "auto" and sys.platform == "win32" else args.ui_mode
    if ui_mode == "auto":
        ui_mode = "live"

    p = pyaudio.PyAudio()

    if args.list_devices:
        list_all_devices(p)
        p.terminate()
        return

    # ── Hardware ───────────────────────────────────────────────────────────
    console.rule("[bold cyan]Tradutor de Audio em Tempo Real - RTX 5060 Ti")
    console.print(f"  {runtime_status_summary()}")

    if args.device:
        device       = args.device
        compute_type = "int8_float16" if device == "cuda" else "int8"
        hw_info      = f"(forcado via --device {device})"
    else:
        device, compute_type, hw_info = detect_device()

    color = "green" if device == "cuda" else "yellow"
    console.print(f"\n  GPU/CPU    : [bold {color}]{device.upper()} {compute_type}[/bold {color}]  {hw_info}")
    console.print(f"  Modelo     : [yellow]{args.model}[/yellow]")
    console.print(f"  Origem     : [yellow]{args.source or 'auto-detect'}[/yellow]")
    console.print(f"  Destino    : [yellow]{args.target}[/yellow]")
    console.print(f"  Interpret. : [yellow]{args.interpretation_mode}[/yellow]")
    console.print(
        f"  Latencia   : [yellow]{tuning.name}[/yellow] "
        f"(chunk={tuning.chunk_seconds:.2f}s, min={tuning.buffer_min_s:.2f}s, "
        f"parcial={tuning.partial_flush_s:.2f}s, flush={tuning.buffer_flush_s:.2f}s)\n"
    )

    # ── Fontes de áudio ────────────────────────────────────────────────────
    rd = find_redragon_devices(p)

    mic_info = mic_notice = spk_info = spk_notice = None
    if not args.no_mic:
        mic_info, mic_notice = select_mic_info(p, args.mic_id, rd["mic"])
    if not args.no_spk:
        spk_info, spk_notice = select_loopback_info(p, args.spk_id, rd["loopback"])

    if mic_notice:
        style = "cyan" if "detectado" in mic_notice else "yellow"
        console.print(f"[{style}]{mic_notice}[/{style}]")
    if spk_notice:
        console.print(f"[cyan]{spk_notice}[/cyan]")
    console.print(f"[dim]Entradas   : mic={'on' if mic_info else 'off'} | sistema={'on' if spk_info else 'off'}[/dim]")

    if not mic_info and not spk_info:
        console.print("[red bold]Nenhuma fonte de audio disponivel.[/red bold]")
        p.terminate()
        sys.exit(1)

    # ── Determina modelo por pipe ──────────────────────────────────────────
    # Quando source=en + loopback ativo, o pipe SPK usa Distil-Whisper EN-only,
    # que é ~4x mais rápido que o modelo padrão para esse cenário específico.
    use_distil_for_spk = bool(spk_info and args.source == "en")
    mic_model_name = args.model
    spk_model_name = args.distil_model if use_distil_for_spk else args.model

    if use_distil_for_spk:
        console.print(
            f"[dim]Perfil system_en ativo: SPK usará [bold]{spk_model_name}[/bold] (EN-only)[/dim]"
        )

    # ── Carrega modelos em paralelo ────────────────────────────────────────
    pipe_model_names: list[str] = []
    if mic_info:
        pipe_model_names.append(mic_model_name)
    if spk_info:
        # Só carrega segunda instância se for modelo diferente ou dois pipes ativos
        if mic_info and spk_model_name == mic_model_name:
            pipe_model_names.append(mic_model_name)   # segunda instância do mesmo
        elif spk_model_name != mic_model_name or not mic_info:
            pipe_model_names.append(spk_model_name)

    console.print(f"[dim]Carregando {len(pipe_model_names)} instancia(s) do modelo em paralelo...[/dim]")
    t_load = time.perf_counter()
    models: list[WhisperModel] = []

    with ThreadPoolExecutor(max_workers=max(1, len(pipe_model_names))) as load_pool:
        futures = [
            load_pool.submit(load_whisper_model, name, device, compute_type)
            for name in pipe_model_names
        ]
        for i, fut in enumerate(futures):
            try:
                models.append(fut.result())
            except Exception as e:
                if device == "cuda" and not models:
                    console.print(f"[red]GPU falhou ({e}), tentando CPU...[/red]")
                    device, compute_type = "cpu", "int8"
                    models.append(load_whisper_model(pipe_model_names[i], "cpu", "int8"))
                elif not models:
                    console.print(f"[red bold]Falha ao carregar modelo: {e}[/red bold]")
                    p.terminate()
                    sys.exit(1)
                else:
                    models.append(models[0])

    load_ms = (time.perf_counter() - t_load) * 1000
    console.print(f"[green][OK] {len(set(id(m) for m in models))} instancia(s) em {load_ms:.0f}ms[/green]")
    console.print("[dim]Aquecendo Whisper/CUDA...[/dim]")
    warm_up_models(models, args.source, tuning)

    # ── Infraestrutura compartilhada ───────────────────────────────────────
    results       : deque[Result] = deque(maxlen=30)
    results_lock   = threading.Lock()
    runtime_state  = {"results_version": 0, "partials": {}}
    ui_queue: Queue[Result] | None = Queue(maxsize=64) if ui_mode == "stable" else None
    trans_cache    = TranslationCache()
    trans_pool     = ThreadPoolExecutor(max_workers=4, thread_name_prefix="translate")
    personal_ctx   = PersonalLanguageContext(CONTEXT_PATH)

    opus_trans = OpusMTTranslator(
        target_lang=args.target,
        device=device,
        compute_type=compute_type,
        models_dir=MODELS_DIR,
    )

    translator = GPUTranslator(
        target_lang=args.target,
        device=device,
        compute_type=compute_type,
        models_dir=MODELS_DIR,
        interpretation_mode=args.interpretation_mode,
        personal_context=personal_ctx,
        opus_translator=opus_trans,
    )
    text_processor  = TextProcessor(translator, trans_cache)
    preload_langs   = [args.source] if args.source else ["en"]
    console.print(f"[dim]Pre-carregando traducao ({', '.join(preload_langs)} -> {args.target})...[/dim]")
    translator.preload(preload_langs)
    console.print(f"[dim]Contexto pessoal: {CONTEXT_PATH.name}[/dim]")

    # ── Pipelines ─────────────────────────────────────────────────────────
    _model_idx = [0]

    def make_pipe(label: str, source_kind: str) -> AudioPipeline:
        # Promove system → system_en quando source=en está fixo:
        # ativa buffers mais agressivos, Distil-Whisper e language lock imediato.
        effective_source_kind = source_kind
        if source_kind == "system" and use_distil_for_spk:
            effective_source_kind = "system_en"

        m = models[min(_model_idx[0], len(models) - 1)]
        _model_idx[0] += 1
        return AudioPipeline(
            label=label, model=m,
            results=results, results_lock=results_lock,
            runtime_state=runtime_state, ui_queue=ui_queue,
            text_processor=text_processor, trans_pool=trans_pool,
            source_lang=args.source, orig_sr=48_000, channels=1,
            tuning=tuning, source_kind=effective_source_kind,
        )

    pipelines:    list[AudioPipeline]  = []
    streams:      list[pyaudio.Stream] = []
    status_parts: list[str]            = []

    if mic_info:
        mic_pipe = make_pipe("MIC", "mic")
        try:
            mic_stream, _, mic_sr, mic_ch = setup_mic(p, mic_info, mic_pipe)
            pipelines.append(mic_pipe)
            streams.append(mic_stream)
            status_parts.append(f"MIC {mic_info['name'][:30]}")
            console.print(f"[green][OK] Microfone[/green]: {mic_info['name']} ({mic_sr}Hz, {mic_ch}ch)")
        except Exception as e:
            console.print(f"[red][ERRO] Microfone: {e}[/red]")

    if spk_info:
        spk_pipe = make_pipe("SISTEMA", "system")
        try:
            spk_stream, _, spk_sr, spk_ch = setup_loopback(p, spk_info, spk_pipe)
            pipelines.append(spk_pipe)
            streams.append(spk_stream)
            status_parts.append(f"SPK {spk_info['name'][:30]}")
            console.print(f"[green][OK] Loopback sistema[/green]: {spk_info['name']} ({spk_sr}Hz, {spk_ch}ch)")
        except Exception as e:
            console.print(f"[red][ERRO] Loopback: {e}[/red]")

    if not pipelines:
        console.print("[red bold]Nenhuma fonte de audio ativa. Encerrando.[/red bold]")
        trans_pool.shutdown(wait=False)
        p.terminate()
        sys.exit(1)

    # ── Inicia ─────────────────────────────────────────────────────────────
    for pipe in pipelines:
        pipe.start()
    for stream in streams:
        stream.start_stream()

    def current_status() -> str:
        pstats = translator.provider_stats if hasattr(translator, 'provider_stats') else None
        return build_runtime_status(device, args.model, tuning, status_parts, pipelines, args.interpretation_mode, provider_stats=pstats)

    status_str = current_status()
    console.print(f"\n[bold green]> ATIVO[/bold green] - [dim]{status_str}[/dim]")
    console.print(f"[dim]UI: {ui_mode} | Ctrl+C para parar[/dim]")

    # ── Overlay (opcional) ─────────────────────────────────────────────────
    overlay = None
    if args.overlay:
        overlay = TranslationOverlay(OverlayConfig())
        overlay.start()
        # Conecta o overlay a todos os pipelines
        for pipe in pipelines:
            pipe.overlay_callback = overlay.push_result
        console.print("[green][OK] Overlay flutuante ativo[/green]")
    console.print()

    # ── Display ────────────────────────────────────────────────────────────
    try:
        if ui_mode == "stable" and ui_queue is not None:
            run_stable_console(ui_queue, args.target, status_str, current_status)
        else:
            run_live_console(results, results_lock, runtime_state, args.target, status_str, current_status)
    except KeyboardInterrupt:
        pass

    # ── Shutdown ───────────────────────────────────────────────────────────
    console.print("\n[dim]Encerrando...[/dim]")
    for pipe in pipelines:
        pipe.stop()
    for stream in streams:
        try:
            stream.stop_stream()
            stream.close()
        except Exception:
            pass
    trans_pool.shutdown(wait=True)
    if overlay:
        overlay.stop()
    p.terminate()
    console.print("[green][OK] Encerrado.[/green]")


if __name__ == "__main__":
    main()
