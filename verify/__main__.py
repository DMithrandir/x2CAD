"""验证台命令行：``python -m verify``。

跑三件事并落一份证据报告：
1. 算子静态检查（``verify/static_check.py`` 的全部规则 + spec 校验）；
2. 算子级 conformance suite（``verify/cases/*.json``）；
3. 覆盖率检查（每个有 spec 的算子都必须有用例）。

退出码：0 = 全绿；1 = 有问题（CI 直接可用）。证据写到 ``verify/evidence/report.json``。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

from verify.conformance import ROOT, check_coverage, load_cases, run_suite
from verify.static_check import check_repo

DEFAULT_EVIDENCE = Path(__file__).resolve().parent / "evidence" / "report.json"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="X2CAD 验证台")
    parser.add_argument("--root", default=str(ROOT), help="仓库根目录")
    parser.add_argument("--cases", default=None, help="用例目录（默认 verify/cases）")
    parser.add_argument("--evidence", default=str(DEFAULT_EVIDENCE), help="证据输出路径")
    parser.add_argument("--quiet", action="store_true", help="只打印汇总")
    args = parser.parse_args(argv)

    root = Path(args.root)
    static_findings = check_repo(root)
    cases = load_cases(Path(args.cases) if args.cases else None)
    missing = check_coverage(root, cases)
    report = run_suite(cases)

    payload = {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "root": str(root),
        "static": {
            "findings": len(static_findings),
            "details": [f.__dict__ for f in static_findings],
        },
        "coverage": {"missing_operators": missing},
        "conformance": report.summary(),
        "failures": [r.as_dict() for r in report.failures()],
    }
    evidence = Path(args.evidence)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    ok = not static_findings and not missing and report.failed == 0
    if not args.quiet:
        print(f"静态检查：{len(static_findings)} 条问题")
        for finding in static_findings:
            print(f"  {finding}")
        if missing:
            print(f"覆盖率缺口：{missing}")
        for failure in report.failures():
            print(f"  FAIL {failure.case_id}[{failure.index}] {failure.kind}: {failure.detail}")
    summary = report.summary()
    print(
        f"conformance：{summary['cases_passed']}/{summary['cases']} cases，"
        f"{summary['checks_passed']}/{summary['checks']} checks；"
        f"证据 {evidence}"
    )
    print("结果：" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
