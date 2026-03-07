#!/usr/bin/env python3
"""
AGX Change Detection Script
偵測哪些模組有改動，用於 CI 決定要構建哪些模組
"""

import os
import sys
import io
import yaml
import json
from pathlib import Path
from typing import Set, List, Dict
import subprocess
import argparse

# Fix Windows Unicode encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


class ChangeDetector:
    """檢測改動的模組"""

    def __init__(self, root_dir: str = ".", config_path: str = ".github/modules.yaml"):
        self.root_dir = Path(root_dir)
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.modules = self._load_modules()

    def _load_config(self) -> Dict:
        """載入配置文件"""
        if self.config_path.exists():
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        return {}

    def _load_modules(self) -> Dict:
        """從配置中載入模組信息"""
        modules = {}
        for name, cfg in self.config.get('modules', {}).items():
            modules[name] = {
                'path': cfg['path'],
                'dockerfiles': cfg.get('dockerfiles', []),
                'critical': cfg.get('critical', False),
                'priority': cfg.get('priority', 999),
            }
        return modules

    def get_changed_modules(self, base_ref: str = "origin/main", head_ref: str = "HEAD") -> Set[str]:
        """
        獲取改動的模組

        Args:
            base_ref: 基準分支 (預設 origin/main)
            head_ref: HEAD 分支 (預設 HEAD)

        Returns:
            改動的模組名稱集合
        """
        changed_modules = set()

        try:
            # 獲取改動的文件
            result = subprocess.run(
                ["git", "diff", "--name-only", base_ref, head_ref],
                cwd=self.root_dir,
                capture_output=True,
                text=True,
                check=False
            )

            if result.returncode != 0:
                print(f"⚠️  Warning: git diff failed: {result.stderr}")
                # 降級：返回所有關鍵模組
                return {name for name, cfg in self.modules.items() if cfg['critical']}

            changed_files = result.stdout.strip().split('\n')

            # 對每個改動的文件，確定屬於哪個模組
            for file_path in changed_files:
                if not file_path:
                    continue

                # 取得文件的頂級目錄
                parts = file_path.split('/')
                if len(parts) == 0:
                    continue

                top_dir = parts[0]

                # 檢查是否匹配任何模組
                for module_name, module_cfg in self.modules.items():
                    module_path = module_cfg['path']

                    # 檢查文件是否屬於此模組
                    if file_path.startswith(module_path + '/') or file_path == module_path:
                        changed_modules.add(module_name)
                        break

                    # 如果是頂級目錄匹配
                    if top_dir == module_path.split('/')[0]:
                        changed_modules.add(module_name)
                        break

        except Exception as e:
            print(f"❌ Error detecting changes: {e}")
            # 降級：返回所有關鍵模組
            return {name for name, cfg in self.modules.items() if cfg['critical']}

        return changed_modules

    def get_dependent_modules(self, changed: Set[str]) -> Set[str]:
        """
        獲取依賴於改動模組的其他模組
        例如：如果 ros1_ws_base 改動，也要重新構建 ros1_ws_bridge 和 ros1_ws_control

        Args:
            changed: 改動的模組集合

        Returns:
            包括依賴模組的完整集合
        """
        all_affected = set(changed)
        queue = list(changed)

        while queue:
            current = queue.pop(0)

            # 找出依賴於 current 的模組
            for module_name, module_cfg in self.modules.items():
                if module_name not in all_affected:
                    # 檢查此模組是否依賴於 current
                    depends_on = self.config.get('modules', {}).get(module_name, {}).get('depends_on', [])
                    if current in depends_on:
                        all_affected.add(module_name)
                        queue.append(module_name)

        return all_affected

    def get_build_priority_order(self, modules: Set[str]) -> List[str]:
        """
        按優先級排序模組以確定構建順序

        Args:
            modules: 要構建的模組集合

        Returns:
            按優先級排序的模組列表
        """
        ranked = []
        for name in modules:
            priority = self.modules.get(name, {}).get('priority', 999)
            ranked.append((priority, name))

        ranked.sort()
        return [name for _, name in ranked]


class CI_MatrixGenerator:
    """生成 GitHub Actions matrix 配置"""

    def __init__(self, detector: ChangeDetector):
        self.detector = detector

    def generate_matrix(self, modules: List[str]) -> Dict:
        """
        為 GitHub Actions 生成 matrix 配置

        Returns:
            matrix 配置字典
        """
        matrix = {
            "module": modules,
            "include": []
        }

        # 為每個模組添加詳細配置
        for module_name in modules:
            module_cfg = self.detector.modules.get(module_name, {})

            include_cfg = {
                "module": module_name,
                "path": module_cfg['path'],
                "dockerfiles": module_cfg.get('dockerfiles', []),
                "critical": module_cfg['critical']
            }

            matrix["include"].append(include_cfg)

        return matrix


def main():
    parser = argparse.ArgumentParser(
        description="AGX Change Detection"
    )
    parser.add_argument(
        "--base",
        default="origin/main",
        help="Base ref for comparison (default: origin/main)"
    )
    parser.add_argument(
        "--head",
        default="HEAD",
        help="Head ref for comparison (default: HEAD)"
    )
    parser.add_argument(
        "--output-json",
        "-o",
        help="Output changed modules as JSON",
        action="store_true"
    )
    parser.add_argument(
        "--output-csv",
        help="Output changed modules as CSV"
    )
    parser.add_argument(
        "--include-deps",
        action="store_true",
        help="Include dependent modules"
    )
    parser.add_argument(
        "--root",
        "-r",
        default=".",
        help="Root directory of the project"
    )
    parser.add_argument(
        "--config",
        default=".github/modules.yaml",
        help="Path to modules configuration"
    )

    args = parser.parse_args()

    # 創建檢測器
    detector = ChangeDetector(args.root, args.config)

    # 檢測改動
    changed = detector.get_changed_modules(args.base, args.head)

    # 如果啟用依賴解析，包括依賴的模組
    if args.include_deps:
        changed = detector.get_dependent_modules(changed)

    # 按優先級排序
    ordered_modules = detector.get_build_priority_order(changed)

    # 輸出結果
    if args.output_json:
        output = {
            "changed_modules": list(changed),
            "ordered_modules": ordered_modules,
            "count": len(changed)
        }
        print(json.dumps(output, indent=2))

    elif args.output_csv:
        with open(args.output_csv, 'w') as f:
            f.write(','.join(ordered_modules))
        print(f"✅ Changed modules written to: {args.output_csv}")

    else:
        # 默認：列印摘要
        print("\n" + "=" * 60)
        print("📊 Change Detection Report")
        print("=" * 60)
        print(f"\nBase:  {args.base}")
        print(f"Head:  {args.head}")
        print(f"\nChanged modules ({len(changed)}):")

        for module in ordered_modules:
            module_cfg = detector.modules.get(module, {})
            critical = "⭐" if module_cfg.get('critical') else "⚪"
            print(f"  {critical} {module}")

        if args.include_deps and len(changed) > 0:
            print("\n✅ Including dependent modules")

        print("\n" + "=" * 60)

        # 為 GitHub Actions 輸出格式
        print(f"\nGitHub Actions output:")
        print(f"  modules={','.join(ordered_modules)}")


if __name__ == "__main__":
    main()
