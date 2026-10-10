"""Read retained native benchmarks; make additive host budgets and nested plots.

No simulation launch, GPU work, runtime modification, or inferred GPU timings.
Requires the existing Isaac Python's NumPy/Matplotlib; inputs stay immutable.
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np


CASES = {
    "source-bound-identity-soak-12": "CPU · 10 000 тиков",
    "source-bound-identity-cpu-14": "CPU · 600 тиков",
    "source-bound-identity-cuda-13": "CUDA · 600 тиков",
}
STAGES = {
    "simulation_advance": ("Симуляция + Kit + ожидания", "#6356a5"),
    "injected_decision_apply": ("Решение + применение команды", "#e49b42"),
    "successor_capture": ("Следующее наблюдение + камеры", "#4b92ba"),
    "causal_commit_and_record": ("Причинная проверка + HDF", "#54a187"),
    "service": ("Служебное + остаток + межтиковый интервал", "#abb1ba"),
}
BUDGETS = {"50_hz": 20.0, "30_hz": 1000 / 30}


def stats(values):
    a = np.asarray(values, dtype=float)
    return dict(
        samples=len(a),
        mean_ms=float(a.mean()),
        **{f"p{p:g}_ms": float(np.percentile(a, p)) for p in (50, 95, 99, 99.9)},
        min_ms=float(a.min()),
        max_ms=float(a.max()),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    sources = {}
    inventory_path = args.root / "retention-inventory.json"
    inventory_bytes = inventory_path.read_bytes()
    inventory = {r["path"]: r for r in json.loads(inventory_bytes)["files"]}

    def read(relative, jsonl=False):
        path = args.root / relative
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        expected = inventory[relative]
        assert digest == expected["sha256"] and len(raw) == expected["bytes"], relative
        sources[relative] = dict(sha256=digest, bytes=len(raw), inventory_match=True)
        return [json.loads(line) for line in raw.splitlines()] if jsonl else json.loads(raw)

    analysis = dict(
        schema="native_tick_budget_analysis_v1",
        input_root=str(args.root),
        retention_inventory_sha256=hashlib.sha256(inventory_bytes).hexdigest(),
        budgets_ms=BUDGETS,
        quest_connected=False,
        new_simulation_runs=0,
        semantics="Host elapsed time incl. waits; no separate GPU execution claim",
        cases={},
        profiles={},
        source_inputs=sources,
    )
    raw_cases = {}
    csv_rows = []
    for name, label in CASES.items():
        rows = read(f"{name}/recording/performance.jsonl", jsonl=True)
        receipt = read(f"{name}/recording/result.json")
        steps = [r for r in rows if r["event"] == "performance_step" and r["post_warmup"]]
        summary = [r for r in rows if r["event"] == "performance_summary"][-1]
        assert not receipt["quest_connected"]
        assert all(b["step"] == a["step"] + 1 for a, b in zip(steps, steps[1:]))
        assert all(
            abs(sum(r["stage_ms"].values()) + r["unattributed_ms"] - r["total_ms"]) < 1e-7
            for r in steps
        )
        # Interval k->k+1 contains body k, its logging, and work before next body.
        # Align the *previous* body with the next start_to_start sample exactly.
        bodies = steps[:-1]
        wall = np.asarray([r["start_to_start_ms"] for r in steps[1:]])
        body = np.asarray([r["total_ms"] for r in bodies])
        gap = wall - body
        assert np.min(gap) >= -0.001, (name, "unexpected clock/alignment overlap")
        aligned = {k: np.asarray([r["stage_ms"][k] for r in bodies]) for k in list(STAGES)[:-1]}
        aligned["service"] = wall - sum(aligned.values())
        assert np.allclose(sum(aligned.values()), wall, atol=1e-9)
        measured = dict(
            label=label,
            warmup_steps=60,
            body_stats=stats([r["total_ms"] for r in steps]),
            wall_stats=stats(wall),
            effective_wall_hz=1000 / wall.mean(),
            encode_tail_hz=receipt["complete_action_and_camera_hz_with_encode_tail"],
            aligned_budget_samples=len(wall),
            between_body_gap=stats(gap),
            stages={},
            budgets={},
        )
        assert abs(measured["effective_wall_hz"] - summary["effective_wall_hz"]) < 1e-9
        for k, values in aligned.items():
            s = stats(values)
            s["share_of_tick_percent"] = 100 * s["mean_ms"] / wall.mean()
            s["share_of_20ms_percent"] = 100 * s["mean_ms"] / 20
            s["share_of_33ms_percent"] = 100 * s["mean_ms"] / BUDGETS["30_hz"]
            measured["stages"][k] = s
            csv_rows.append(dict(case=name, stage=k, **s))
        for k, budget in BUDGETS.items():
            measured["budgets"][k] = dict(
                budget_ms=budget,
                exceeded_count=int(np.sum(wall > budget)),
                exceeded_fraction=float(np.mean(wall > budget)),
                signed_headroom_ms={
                    p: budget - measured["wall_stats"][p]
                    for p in ("mean_ms", "p50_ms", "p95_ms", "p99_ms", "max_ms")
                },
                extra_serial_cost_at_95_percent_on_time_ms=budget - float(np.percentile(wall, 95)),
            )
        # Keep the rarest slow ticks, including their stage attribution.
        measured["slowest_body_ticks"] = sorted(steps, key=lambda r: r["total_ms"], reverse=True)[
            :10
        ]
        analysis["cases"][name] = measured
        raw_cases[name] = dict(wall=wall, bodies=bodies, aligned=aligned)

    # Detailed observers exist in earlier profiles, not the final identity/cache
    # recipe. Never transfer their component timings into that recipe's budget.
    for name in (
        "source-bound-profile-04",
        "source-bound-attribute-profile-08",
        "profile-default-01",
        "gpu-retained-profile-01",
    ):
        rows = read(f"{name}/recording/performance.jsonl", jsonl=True)
        steps = [r for r in rows if r["event"] == "performance_step" and r["post_warmup"]]
        profile = read(f"{name}/recording/native-profile.json")
        lo = steps[0]["monotonic_ns"] - round(steps[0]["total_ms"] * 1e6)
        hi = steps[-1]["monotonic_ns"]
        observed = [
            r
            for r in profile["rows"]
            if r["begin_monotonic_ns"] >= lo and r["end_monotonic_ns"] <= hi
        ]
        assert all(r["succeeded"] for r in observed)
        assert len({r["thread_id"] for r in observed}) == 1
        metrics = {}
        for stage in sorted({r["stage"] for r in observed}):
            events = [r for r in observed if r["stage"] == stage]
            metrics[stage] = dict(
                calls=len(events),
                ms_per_tick=sum(r["duration_ns"] for r in events) / 1e6 / len(steps),
                **stats([r["duration_ns"] / 1e6 for r in events]),
            )
        # Validate actual timestamp containment, not names alone, before subtracting.
        parent_map = {
            "snapshot_recordables": "canonical_observation",
            "rendered_source_comparison": "native_result_callback",
        }
        containment = {}
        for child, parent in parent_map.items():
            children = [r for r in observed if r["stage"] == child]
            parents = [r for r in observed if r["stage"] == parent]
            if children:
                containment[child] = all(
                    sum(
                        p["begin_monotonic_ns"] <= c["begin_monotonic_ns"]
                        and c["end_monotonic_ns"] <= p["end_monotonic_ns"]
                        for p in parents
                    )
                    == 1
                    for c in children
                )
                assert containment[child], (name, child)
        outer = [r for r in observed if r["stage"] not in parent_map]
        ordered = sorted(outer, key=lambda r: r["begin_monotonic_ns"])
        assert all(
            a["end_monotonic_ns"] <= b["begin_monotonic_ns"] for a, b in zip(ordered, ordered[1:])
        ), (name, "outer observer overlap")
        summary = [r for r in rows if r["event"] == "performance_summary"][-1]
        analysis["profiles"][name] = dict(
            steady_ticks=len(steps),
            metrics=metrics,
            nested_containment_verified=containment,
            outer_observers_disjoint=True,
            body_stats=stats([r["total_ms"] for r in steps]),
            top_stages=summary["stages"],
            nested_stages_not_additive=summary["nested_stages_not_additive"],
            cprofile=bool(profile["cprofile"]),
            final_identity_cache_recipe=False,
            run_passed=name != "profile-default-01",
            known_failure="cleanup setting restoration" if name == "profile-default-01" else None,
        )

    analysis["limitations"] = [
        "All cases no real Quest; injected input cost is not real XR input/network/compositor cost.",
        "Unpaced throughput; one tick = one decision + four 120Hz substeps = 33.33ms simulation time.",
        "Final recipe has coarse host timings only. Physics/RTX/GPU execution cannot be separated from them.",
        "NVENC submission is not encode GPU time; render/preview/callbacks already included in parents.",
        "Mean partitions are additive; p95/p99 component values are not additive.",
        "Serial extra-cost scenario is arithmetic headroom, not a headset performance prediction.",
        "No new simulation or GPU tests. Original source-quality/physics/host-RAM limitations remain.",
    ]
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.facecolor": "#fafbfc",
            "axes.facecolor": "#fafbfc",
        }
    )
    figures = []
    fig, axes = plt.subplots(1, 2, figsize=(15, 6), gridspec_kw={"width_ratios": [1.65, 1]})
    names = list(CASES)
    left = np.zeros(len(names))
    for stage, (label, color) in STAGES.items():
        values = [analysis["cases"][n]["stages"][stage]["mean_ms"] for n in names]
        axes[0].barh(range(len(names)), values, left=left, color=color, label=label, height=0.56)
        for i, v in enumerate(values):
            if v >= 1:
                axes[0].text(
                    left[i] + v / 2,
                    i,
                    f"{v:.1f}",
                    ha="center",
                    va="center",
                    color="white",
                    fontweight="bold",
                    fontsize=9,
                )
        left += values
    for ax in axes:
        ax.set_yticks(range(len(names)), [CASES[n] for n in names])
        ax.invert_yaxis()
        ax.grid(axis="x", alpha=0.15)
    for budget, color in ((20, "#b64949"), (1000 / 30, "#458768")):
        axes[0].axvline(budget, linestyle="--", color=color)
        axes[0].text(budget + 0.25, -0.5, f"{budget:.2f} мс", color=color)
    for i, n in enumerate(names):
        axes[0].text(left[i] + 0.25, i, f"{left[i]:.2f} мс", va="center", fontsize=10)
    axes[0].set_xlim(0, 45)
    axes[0].set_xlabel("Среднее время между стартами соседних тиков, мс")
    axes[0].set_title("Распределение времени без двойного счёта", pad=28)
    axes[0].legend(loc="upper left", bbox_to_anchor=(0, -0.17), fontsize=9)
    y = np.arange(len(names))
    for offset, (key, label, color) in zip(
        (-0.16, 0.16),
        [
            ("50_hz", "Бюджет 20 мс · 50 Гц", "#b64949"),
            ("30_hz", "Бюджет 33,33 мс · 30 Гц", "#458768"),
        ],
    ):
        values = [
            analysis["cases"][n]["budgets"][key]["signed_headroom_ms"]["mean_ms"] for n in names
        ]
        axes[1].barh(y + offset, values, height=0.28, color=color, label=label)
        for i, v in enumerate(values):
            axes[1].text(
                v + (0.3 if v >= 0 else -0.3),
                i + offset,
                f"{v:+.2f}",
                va="center",
                ha="left" if v >= 0 else "right",
                fontsize=10,
            )
    axes[1].axvline(0, color="#555", linewidth=0.8)
    axes[1].set_xlim(-24, 18)
    axes[1].set_title("Запас / перерасход среднего бюджета", pad=28)
    axes[1].set_xlabel("Свободное время, мс; минус = перерасход")
    axes[1].legend(loc="upper left", bbox_to_anchor=(0, -0.17), fontsize=9)
    fig.suptitle(
        "Live-запись без Quest: три камеры 960×600 + HDF + NVENC + превью",
        fontsize=15,
        fontweight="bold",
    )
    fig.subplots_adjust(left=0.14, right=0.98, bottom=0.29, wspace=0.55, top=0.79)
    figures.append(("tick_breakdown", fig))

    fig, axes = plt.subplots(1, 2, figsize=(15, 6.5))
    colors = ("#6356a5", "#4b92ba", "#e49b42")
    extra = np.linspace(0, 18, 181)
    for n, color in zip(names, colors):
        wall = raw_cases[n]["wall"]
        ordered = np.sort(wall)
        axes[0].plot(
            ordered,
            np.arange(1, len(wall) + 1) / len(wall) * 100,
            color=color,
            label=CASES[n],
            lw=2,
        )
        axes[1].plot(
            extra,
            [np.mean(wall + x <= 1000 / 30) * 100 for x in extra],
            color=color,
            label=CASES[n],
            lw=2,
        )
    for budget, color in ((20, "#b64949"), (1000 / 30, "#458768")):
        axes[0].axvline(budget, color=color, ls="--")
        axes[0].text(budget + 0.35, 5, f"{budget:.2f} мс", color=color, rotation=90)
    axes[0].set(
        xlim=(15, 52),
        ylim=(0, 101),
        xlabel="Время между стартами тиков, мс",
        ylabel="Доля тиков не медленнее X, %",
        title="Распределение, включая медленные тики",
    )
    axes[0].legend(loc="lower right", fontsize=9)
    axes[1].axhline(95, color="#777", ls=":")
    axes[1].set(
        xlim=(0, 18),
        ylim=(0, 101),
        xlabel="Гипотетическая дополнительная последовательная работа, мс",
        ylabel="Доля тиков в бюджете 33,33 мс, %",
        title="Чувствительность к добавленной стоимости",
    )
    axes[1].legend(loc="lower left", fontsize=9)
    for ax in axes:
        ax.grid(alpha=0.2)
    text = []
    for n in names:
        case = analysis["cases"][n]
        w = case["wall_stats"]
        text.append(
            f"{CASES[n]}: p95 {w['p95_ms']:.2f}; p99 {w['p99_ms']:.2f}; max {w['max_ms']:.2f} мс. "
            f">20 мс: {100 * case['budgets']['50_hz']['exceeded_fraction']:.2f}%; "
            f">33,33 мс: {100 * case['budgets']['30_hz']['exceeded_fraction']:.3f}%"
        )
    fig.text(0.07, 0.075, "\n".join(text), fontsize=10)
    fig.text(
        0.07,
        0.025,
        "Редкий максимум soak 179 мс вне масштаба CDF, включён в статистику. Сценарий справа — арифметика, не замер Quest.",
        fontsize=9,
        color="#555",
    )
    fig.suptitle(
        "Бюджет определяется также разбросом, а не только средним FPS",
        fontsize=16,
        fontweight="bold",
    )
    fig.subplots_adjust(bottom=0.25, top=0.82, wspace=0.3)
    figures.append(("budget_distribution", fig))

    n = "source-bound-attribute-profile-08"
    p = analysis["profiles"][n]
    m = {k: v["ms_per_tick"] for k, v in p["metrics"].items()}
    advance = p["top_stages"]["simulation_advance"]["mean_ms"]
    successor = p["top_stages"]["successor_capture"]["mean_ms"]
    enc = sum(v for k, v in m.items() if k.startswith("encoder_submit_role"))
    parts = [
        [
            ("Публикация источника", m["native_source_publication"], "#e49b42"),
            ("USD/Fabric sync", m["added_usd_fabric_sync"], "#abb1ba"),
            ("RGB callbacks, 3 камеры", m["native_result_callback"], "#4b92ba"),
            (
                "Остальная симуляция / Kit / ожидания",
                advance
                - m["native_source_publication"]
                - m["added_usd_fabric_sync"]
                - m["native_result_callback"],
                "#6356a5",
            ),
        ],
        [
            ("Snapshot recordables", m["snapshot_recordables"], "#6356a5"),
            (
                "Остальной canonical observation",
                m["canonical_observation"] - m["snapshot_recordables"],
                "#aa95d0",
            ),
            ("NVENC submit, 3 камеры", enc, "#e49b42"),
            ("Preview publish", m["preview_publish"], "#54a187"),
            (
                "Другой capture / binding / JSONL / HDF",
                successor - m["canonical_observation"] - enc - m["preview_publish"],
                "#abb1ba",
            ),
        ],
        [
            ("Сверка source ID / камеры", m["rendered_source_comparison"], "#54a187"),
            (
                "Остальной RGB callback, включая copy/wait",
                m["native_result_callback"] - m["rendered_source_comparison"],
                "#4b92ba",
            ),
        ],
    ]
    assert all(v >= 0 for group in parts for _, v, _ in group)
    analysis["profiles"][n]["exclusive_partitions_ms_per_tick"] = {
        title: {label: value for label, value, _ in group}
        for title, group in zip(
            ("simulation_advance", "successor_capture", "native_result_callback"), parts
        )
    }
    fig, axes = plt.subplots(3, 1, figsize=(13, 8))
    titles = [
        f"Внутри simulation_advance · {advance:.3f} мс/тик",
        f"Внутри successor_capture · {successor:.3f} мс/тик",
        f"Внутри RGB callbacks · {m['native_result_callback']:.3f} мс/тик · уже входят в верхнюю полосу",
    ]
    for ax, group, title in zip(axes, parts, titles):
        left = 0
        for label, v, color in group:
            ax.barh([0], [v], left=left, color=color, height=0.45, label=f"{label}: {v:.3f} мс")
            if v > 0.18:
                ax.text(
                    left + v / 2,
                    0,
                    f"{v:.2f}",
                    ha="center",
                    va="center",
                    color="white",
                    fontsize=9,
                )
            left += v
        ax.set(yticks=[], xlabel="мс на управляющий тик", title=title, xlim=(0, left * 1.035))
        ax.legend(loc="upper left", bbox_to_anchor=(0, -0.48), ncol=2, fontsize=9)
        ax.grid(axis="x", alpha=0.15)
    fig.suptitle(
        "Детальный host-профиль прежнего Attribute + camera QA режима",
        fontsize=16,
        fontweight="bold",
    )
    fig.text(
        0.07,
        0.025,
        "Это отдельный профиль, 48,01 Гц; не финальный identity/cache ~50 Гц. Полосы разных уровней нельзя складывать.\nGPU encode/render не измерены отдельно. USD/Fabric sync 0,025 мс — отдельный вызов перед публикацией источника.",
        fontsize=10,
        color="#555",
    )
    fig.subplots_adjust(top=0.87, bottom=0.18, hspace=1.8)
    figures.append(("nested_profile", fig))
    soak = raw_cases["source-bound-identity-soak-12"]
    wall = soak["wall"]
    elapsed_s = (np.cumsum(wall) - wall) / 1000
    late = np.flatnonzero(wall > BUDGETS["30_hz"])
    analysis["cases"]["source-bound-identity-soak-12"]["over_30hz_budget_intervals"] = [
        dict(
            body_step=soak["bodies"][i]["step"],
            interval_ms=float(wall[i]),
            stages_ms={k: float(v[i]) for k, v in soak["aligned"].items()},
        )
        for i in late
    ]
    fig, axes = plt.subplots(1, 2, figsize=(15, 6.8), gridspec_kw={"width_ratios": [1, 1.2]})
    axes[0].plot(elapsed_s, wall, color="#6356a5", linewidth=0.7)
    axes[0].scatter(elapsed_s[late], wall[late], color="#b64949", s=22, zorder=3)
    for budget, color in ((20, "#b64949"), (1000 / 30, "#458768")):
        axes[0].axhline(budget, color=color, ls="--", alpha=0.65)
    worst = int(np.argmax(wall))
    axes[0].annotate(
        f"{wall[worst]:.2f} мс\n159,54 мс: causal commit / record",
        xy=(elapsed_s[worst], wall[worst]),
        xytext=(45, 155),
        arrowprops=dict(arrowstyle="->", color="#b64949"),
        fontsize=10,
    )
    axes[0].set(
        xlabel="Время от начала измеряемого окна, с",
        ylabel="Интервал между стартами тиков, мс",
        ylim=(0, 200),
        title="10 000 управляющих тиков: редкие задержки",
    )
    left = np.zeros(len(late))
    for stage, (label, color) in STAGES.items():
        values = soak["aligned"][stage][late]
        axes[1].barh(range(len(late)), values, left=left, color=color, label=label, height=0.6)
        for i, v in enumerate(values):
            if v > 10:
                axes[1].text(
                    left[i] + v / 2,
                    i,
                    f"{v:.1f}",
                    ha="center",
                    va="center",
                    color="white",
                    fontsize=9,
                )
        left += values
    axes[1].set(
        yticks=range(len(late)),
        yticklabels=[f"Тик {soak['bodies'][i]['step']}" for i in late],
        xlabel="Время между стартами тиков, мс",
        title="Все 7 интервалов, превышающих 33,33 мс",
        xlim=(0, 191),
    )
    axes[1].invert_yaxis()
    axes[1].axvline(1000 / 30, color="#458768", ls="--")
    for i, v in enumerate(left):
        axes[1].text(v + 0.8, i, f"{v:.2f}", va="center", fontsize=9)
    for ax in axes:
        ax.grid(alpha=0.15)
    handles, labels = axes[1].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, 0.04), ncol=2, fontsize=9)
    fig.suptitle(
        "Среднее ограничивает симуляция / Kit; самый тяжёлый выброс — путь записи",
        fontsize=15,
        fontweight="bold",
    )
    fig.subplots_adjust(left=0.07, right=0.97, top=0.82, bottom=0.28, wspace=0.4)
    figures.append(("slow_ticks", fig))
    with PdfPages(
        args.output / "tick_budget.pdf",
        metadata={
            "Title": "Native live tick budgets",
            "Author": "vla_infrastructure",
            "CreationDate": None,
            "ModDate": None,
        },
    ) as pdf:
        for name, fig in figures:
            fig.savefig(args.output / f"{name}.png", dpi=160)
            pdf.savefig(fig)
            plt.close(fig)
    with (args.output / "stage_timings.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(csv_rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(csv_rows)
    (args.output / "analysis.json").write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2) + "\n"
    )
    artifacts = {
        p.name: dict(bytes=p.stat().st_size, sha256=hashlib.sha256(p.read_bytes()).hexdigest())
        for p in args.output.iterdir()
    }
    (args.output / "analysis_receipt.json").write_text(
        json.dumps(
            dict(
                command=[sys.executable, *sys.argv],
                script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                artifacts=artifacts,
                input_files_verified=len(sources),
                checks="PASS: source SHA/size, additive closure, warmup exclusion, sample alignment, nested timestamp containment, no overlap",
                new_simulation_runs=0,
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(
        json.dumps(
            {
                k: dict(wall_ms=v["wall_stats"], budgets=v["budgets"])
                for k, v in analysis["cases"].items()
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
