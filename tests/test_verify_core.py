"""验证台自身的 oracle：Tier 1 不变量、解析真值、鲁棒性平面、静态检查器、spec 校验。

元纪律：验证台也必须被验证——这里对检查器注入**已知坏样本**，要求它必须抓到；
抓不到的检查器和没有检查器一样危险（设计文档 §7.4 的同一条逻辑，先在小尺度上执行）。
"""

import json
import math
from pathlib import Path

import pytest

from primitives.bspline import DomainError
from verify import analytic, invariants
from verify.conformance import check_coverage, load_cases, run_suite
from verify.robustness import PlaneRow, random_rotation_2d, rigid_transform_2d, run_plane
from verify.spec_check import validate_spec
from verify.static_check import check_operator_dir, check_repo, check_source, format_findings

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- Tier 1


def test_partition_of_unity_known_knot_vectors():
    assert invariants.partition_of_unity_residual([0.0, 0.0, 0.0, 1.0, 1.0, 1.0], 2, 0.37) < 1e-15
    assert invariants.partition_of_unity_residual([0.0, 0.0, 0.0, 0.5, 1.0, 1.0, 1.0], 2, 0.5) < 1e-15


def test_derivative_partition_is_zero():
    U = [0.0, 0.0, 0.0, 0.5, 1.0, 1.0, 1.0]
    assert invariants.derivative_partition_residual(U, 2, 0.3, 1) < 1e-14


def test_closed_manifold_accepts_oriented_tetrahedron():
    faces = [(0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)]
    assert invariants.closed_manifold_problems(faces) == []
    v, e, f, chi = invariants.euler_characteristic(faces)
    assert (v, e, f, chi) == (4, 6, 4, 2)


def test_closed_manifold_detects_missing_face():
    faces = [(0, 2, 1), (0, 1, 3), (1, 2, 3)]  # 少一个面 → 边界
    problems = invariants.closed_manifold_problems(faces)
    assert len(problems) == 3
    assert all("应为 2" in p for p in problems)


def test_closed_manifold_detects_inconsistent_orientation():
    faces = [(0, 2, 1), (0, 1, 3), (1, 2, 3), (0, 2, 3)]  # 最后一面翻转
    problems = invariants.closed_manifold_problems(faces)
    assert any("方向相同" in p or "法向" in p for p in problems)


def test_euler_characteristic_two_components():
    faces = [
        (0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3),
        (4, 6, 5), (4, 5, 7), (5, 6, 7), (6, 4, 7),
    ]
    v, e, f, chi = invariants.euler_characteristic(faces)
    assert (v, e, f) == (8, 12, 8)
    assert chi == 4


def test_degenerate_triangle_detection():
    points = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    assert invariants.degenerate_triangle_count(points, [(0, 1, 2)]) == 1
    assert invariants.degenerate_triangle_count(points, [(0, 1, 3)]) == 0


# ---------------------------------------------------------------- Tier 2


def test_relative_error_definition():
    assert analytic.rel_error(1.0, 0.0) == math.inf
    assert analytic.rel_error(0.0, 0.0) == 0.0
    assert analytic.rel_error(1.01, 1.0) == pytest.approx(0.01)


def test_analytic_closed_forms():
    assert analytic.circle_circumference(2.0) == pytest.approx(4.0 * math.pi)
    assert analytic.sphere_volume(1.0) == pytest.approx(4.0 / 3.0 * math.pi)
    assert analytic.cube_volume(3.0) == pytest.approx(27.0)


# ---------------------------------------------------------------- Tier 4


def _distance_case(scale, offset, tol, rng):
    rot = random_rotation_2d(rng)
    base = [(0.0 + offset, 0.0), (1.0 + offset, 0.0)]
    pts = rigid_transform_2d(base, rot, (0.3 * scale, -0.2 * scale))
    return {"pts": [(x * scale, y * scale) for x, y in pts], "scale": scale}


def test_robustness_plane_default_domain_is_fully_green():
    result = run_plane(
        "distance",
        _distance_case,
        lambda o: math.dist(o["pts"][0], o["pts"][1]),
        lambda o: o["scale"],
        seeds=(0, 1),
        scales=(1e-1, 1.0, 1e3),
        offsets=(0.0, 1e-9, 1e-6),
        tolerances=(1e-12,),
        threshold=1e-9,
    )
    assert result.default_domain_pass_rate() == 1.0
    assert result.unlabeled_failures() == []
    summary = result.summary()
    assert summary["cells"] == 2 * 3 * 3 * 1


def test_robustness_plane_catches_scaling_bug():
    result = run_plane(
        "distance-scaled-wrong",
        _distance_case,
        lambda o: math.dist(o["pts"][0], o["pts"][1]) * 1.0001,
        lambda o: o["scale"],
        scales=(1e-1, 1.0, 1e3),
        offsets=(0.0,),
        tolerances=(1e-12,),
        threshold=1e-9,
    )
    assert result.default_domain_pass_rate() == 0.0
    assert result.worst_error() > 1e-5


def test_robustness_plane_labels_explicit_rejections():
    def build(scale, offset, tol, rng):
        if offset >= 1e-2:
            raise DomainError("超出可接受位错")
        return _distance_case(scale, offset, tol, rng)

    result = run_plane(
        "rejecting",
        build,
        lambda o: math.dist(o["pts"][0], o["pts"][1]),
        lambda o: o["scale"],
        seeds=(0,),
        scales=(1.0,),
        offsets=(0.0, 1e-2),
        tolerances=(1e-12,),
        threshold=1e-9,
        family=lambda o: "N",
    )
    assert result.boundary_pass_rate() == 0.0
    assert result.unlabeled_failures() == []
    assert all(r.family == "FAIL" for r in result.rows if not r.ok)


def test_plane_csv_written(tmp_path):
    result = run_plane(
        "csv",
        _distance_case,
        lambda o: math.dist(o["pts"][0], o["pts"][1]),
        lambda o: o["scale"],
        seeds=(0,),
        scales=(1.0,),
        offsets=(0.0,),
        tolerances=(1e-12,),
    )
    path = tmp_path / "plane.csv"
    result.to_csv(path)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("seed,scale,offset_ratio,tol,error,ok,family")
    assert len(text.strip().splitlines()) == 2


# ---------------------------------------------------------------- 静态检查器


def test_static_check_catches_swallowed_exception():
    findings = check_source("def f(x):\n    try:\n        return 1 / x\n    except Exception:\n        pass\n")
    assert [f.rule for f in findings] == ["SC001"]


def test_static_check_catches_nondeterminism_and_io():
    assert [f.rule for f in check_source("import random\n")] == ["SC002"]
    assert "SC003" in [f.rule for f in check_source("def f(x):\n    print(x)\n    return x\n")]


def test_static_check_catches_float_literal_equality():
    findings = check_source("def f(x):\n    return x == 0.5\n")
    assert [f.rule for f in findings] == ["SC004"]
    # 与节点值比较（非常量）不误报；x == 0.0 是"精确为零"的退化守卫，放行
    assert check_source("def f(x, U, n):\n    return x == U[n + 1]\n") == []
    assert check_source("def f(x):\n    return x == 0.0\n") == []


def test_static_check_catches_private_cross_operator_import():
    findings = check_source("from operators.curve_eval.impl import _check_ctrl\n")
    assert [f.rule for f in findings] == ["SC005"]


def test_static_check_passes_clean_implementation():
    clean = (
        "from primitives.bspline import DomainError\n"
        "def f(x, tol=1e-12):\n"
        "    if x > 0.0:\n"
        "        return x\n"
        "    raise DomainError('x<=0')\n"
    )
    assert check_source(clean) == []


def test_repo_operators_are_static_clean():
    findings = check_repo(ROOT)
    assert findings == [], format_findings(findings)


# ---------------------------------------------------------------- spec 校验


def _valid_spec():
    return {
        "slug": "demo_op",
        "name": "Demo operator",
        "category": "curve",
        "dim": "2D",
        "version": "0.1.0",
        "source": "unit test",
        "signature": {"inputs": {"x": "float"}, "outputs": ["y: float"]},
        "preconditions": ["x 有限"],
        "invariants": ["y == x"],
        "degeneracy_branches": [{"family": "N", "trigger": "x=0", "action": "FAIL: DomainError"}],
        "oracle_tests": "tests/test_demo.py",
    }


def test_valid_spec_passes():
    assert validate_spec(_valid_spec(), expected_slug="demo_op") == []


def test_spec_missing_field_is_reported():
    spec = _valid_spec()
    del spec["invariants"]
    assert any("invariants" in p for p in validate_spec(spec))


def test_spec_bad_family_is_reported():
    spec = _valid_spec()
    spec["degeneracy_branches"] = [{"family": "X", "trigger": "t", "action": "a"}]
    assert any("五族" in p for p in validate_spec(spec))


def test_spec_bad_category_is_reported():
    spec = _valid_spec()
    spec["category"] = "nonsense"
    assert any("category" in p for p in validate_spec(spec))


def test_undeclared_dependency_is_reported(tmp_path):
    op = tmp_path / "operators" / "demo_op"
    op.mkdir(parents=True)
    spec = _valid_spec()
    (op / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    (op / "impl.py").write_text("from operators.other.impl import helper\n", encoding="utf-8")
    (tmp_path / "operators" / "other").mkdir()
    findings = check_operator_dir(op)
    assert any(f.rule == "SC006" for f in findings), findings


# ---------------------------------------------------------------- conformance


def test_conformance_suite_is_green():
    report = run_suite()
    assert report.failed == 0, [r.as_dict() for r in report.failures()]
    assert report.summary()["cases"] >= 10


def test_every_operator_has_conformance_cases():
    assert check_coverage(ROOT) == []


def test_case_files_are_well_formed():
    cases = load_cases()
    ids = [c["case_id"] for c in cases]
    assert len(ids) == len(set(ids))
    for case in cases:
        assert case["checks"], case["case_id"]


def test_report_serializes(tmp_path):
    report = run_suite()
    path = tmp_path / "report.json"
    report.write_json(path)
    blob = json.loads(path.read_text(encoding="utf-8"))
    assert blob["summary"]["checks_failed"] == 0
    assert len(blob["results"]) == len(report.results)


def test_plane_row_is_hashable_and_serializable():
    row = PlaneRow(0, 1.0, 0.0, 1e-12, 1e-15, True)
    assert row.as_dict()["ok"] is True
