"""Diff the snapshot's b.ai-routed models against the screenshots.

Expected (from the user's screenshots at chat.b.ai/key):

FREE (input=0 AND output=0):
  DeepSeek-V4-Flash
  DeepSeek-V4-Flash-Vision-Exp
  Hy3  (Tencent)
  MiMo-V2.5  (Xiaomi)
  GLM-5.3-Flash  (Z.ai)
  Qwen3.8-Flash  (Alibaba)

PAID (others):
  DeepSeek-V4-Pro: 1.32 / 1.32 / 0.044 / 3.96
  Hy4-preview: 0.834 / 0.834 / 0.0417 / 2.501
  MiMo-V2.5-Pro: 0.435 / 0.435 / 0.0036 / 0.87
  GLM-5.3 / 5.2 / 5.1: 1.4 / 1.4 / 0.28 / 4.4
  Qwen3.8-Max: 2 / 2 / 0.25 / 6
  Qwen3.8-27B: 0.22 / 0.22 / 0.022 / 1.6
  Claude Opus 5: 5 / 6.25 / 0.5 / 25
  Claude Fable 5: 10 / 12.5 / 1 / 50
  Claude Opus 4.8/4.7/4.6/4.5: 5 / 6.25 / 0.5 / 25
  Claude Sonnet 5: 2 / 2.5 / 0.2 / 10
  Claude Sonnet 4.6/4.5: 3 / 3.75 / 0.3 / 15
  Claude Haiku 4.5: 1 / 1.25 / 0.1 / 5
  GPT-5.6 Sol: 4 / 5 / 0.4 / 20
  GPT-5.6 Terra: 2 / 2.5 / 0.2 / 12
  GPT-5.6 Luna: 0.2 / 0.25 / 0.02 / 1.2
  GPT-5.5: 5 / 5 / 0.5 / 30
  GPT-5.5-Instant: 5 / 5 / 0.5 / 30
  GPT-5.4: 2.5 / 2.5 / 0.25 / 15
  GPT-5.2: 1.75 / 1.75 / 0.175 / 14
  GPT-5.4 Pro: 30 / 30 / 3 / 180
  GPT-5.4 mini: 0.75 / 0.75 / 0.075 / 4.5
  GPT-5 mini: 0.25 / 0.25 / 0.025 / 2
  GPT-5.4 nano: 0.2 / 0.2 / 0.02 / 1.25
  GPT-5 nano: 0.05 / 0.05 / 0.005 / 0.4
  Gemini 3.1 Pro: 2 / 2 / 0.2 / 12
  Gemini 3.5 flash: 1.5 / 1.5 / 0.15 / 9
  Gemini 3 Flash: 0.5 / 0.5 / 0.05 / 3
  Gemini 3.5 flash-lite: 0.3 / 0.3 / 0.03 / 2.5
  Gemini 3.6 flash: 1.5 / 1.5 / 0.15 / 7.5
  MiniMax-M3: 0.3 / 0.3 / 0.06 / 1.2
  MiniMax-M2.7: 0.3 / 0.375 / 0.06 / 1.2
  Kimi-K2.6: 0.95 / 0.95 / 0.1615 / 4
  Kimi K3: 3 / 3 / 0.3 / 15
"""
import json
from pathlib import Path

EXPECTED_FREE = {"DeepSeek-V4-Flash", "DeepSeek-V4-Flash-Vision-Exp", "Hy3",
                 "MiMo-V2.5", "GLM-5.3-Flash", "Qwen3.8-Flash"}
EXPECTED_PRICING = {
    "DeepSeek-V4-Pro": (1.32, 1.32, 0.044, 3.96),
    "Hy4-preview": (0.834, 0.834, 0.0417, 2.501),
    "MiMo-V2.5-Pro": (0.435, 0.435, 0.0036, 0.87),
    "GLM-5.3": (1.4, 1.4, 0.28, 4.4),
    "GLM-5.2": (1.4, 1.4, 0.28, 4.4),
    "GLM-5.1": (1.4, 1.4, 0.28, 4.4),
    "Qwen3.8-Max": (2, 2, 0.25, 6),
    "Qwen3.8-27B": (0.22, 0.22, 0.022, 1.6),
    "Claude-Opus-5": (5, 6.25, 0.5, 25),
    "Claude-Fable-5": (10, 12.5, 1, 50),
    "Claude-Opus-4.8": (5, 6.25, 0.5, 25),
    "Claude-Opus-4.7": (5, 6.25, 0.5, 25),
    "Claude-Opus-4.6": (5, 6.25, 0.5, 25),
    "Claude-Opus-4.5": (5, 6.25, 0.5, 25),
    "Claude-Sonnet-5": (2, 2.5, 0.2, 10),
    "Claude-Sonnet-4.6": (3, 3.75, 0.3, 15),
    "Claude-Sonnet-4.5": (3, 3.75, 0.3, 15),
    "Claude-Haiku-4.5": (1, 1.25, 0.1, 5),
    "GPT-5.6-Sol": (4, 5, 0.4, 20),
    "GPT-5.6-Terra": (2, 2.5, 0.2, 12),
    "GPT-5.6-Luna": (0.2, 0.25, 0.02, 1.2),
    "GPT-5.5": (5, 5, 0.5, 30),
    "GPT-5.5-Instant": (5, 5, 0.5, 30),
    "GPT-5.4": (2.5, 2.5, 0.25, 15),
    "GPT-5.2": (1.75, 1.75, 0.175, 14),
    "GPT-5.4-Pro": (30, 30, 3, 180),
    "GPT-5.4-mini": (0.75, 0.75, 0.075, 4.5),
    "GPT-5-mini": (0.25, 0.25, 0.025, 2),
    "GPT-5.4-nano": (0.2, 0.2, 0.02, 1.25),
    "GPT-5-nano": (0.05, 0.05, 0.005, 0.4),
    "Gemini-3.1-Pro": (2, 2, 0.2, 12),
    "Gemini-3.5-flash": (1.5, 1.5, 0.15, 9),
    "Gemini-3-Flash": (0.5, 0.5, 0.05, 3),
    "Gemini-3.5-flash-lite": (0.3, 0.3, 0.03, 2.5),
    "Gemini-3.6-flash": (1.5, 1.5, 0.15, 7.5),
    "MiniMax-M3": (0.3, 0.3, 0.06, 1.2),
    "MiniMax-M2.7": (0.3, 0.375, 0.06, 1.2),
    "Kimi-K2.6": (0.95, 0.95, 0.1615, 4),
    "Kimi-K3": (3, 3, 0.3, 15),
}

snap = json.loads(Path("data/snapshot.json").read_text(encoding="utf-8"))
# All models whose origin is b.ai: either p_bai itself or routed to a known upstream.
bai_models = [m for m in snap["models"] if m.get("source") == "bai" or m["provider_id"] == "p_bai"
              or (m.get("input_per_1m") and any(t in m["display_name"] for t in ("GLM 5", "Qwen 3.8", "Gemini 3", "Claude Opus", "Claude Sonnet", "Claude Haiku", "GPT-5", "DeepSeek V4", "Hunyuan", "MiMo", "MiniMax", "Kimi K")))]
# Easier: just dump everything and let me compare manually.
print("All b.ai-routed models in current snapshot:")
for m in snap["models"]:
    inp = m.get("input_per_1m")
    if inp is None:
        continue
    print(f"  {m['model_id']:30s}  prov={m['provider_id']:18s}  in=${inp}  out=${m.get('output_per_1m')}  free={m['is_free']}")
