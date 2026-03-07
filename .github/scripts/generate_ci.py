#!/usr/bin/env python3
"""
AGX Modular CI Generator
自動檢測 Dockerfile 並生成模組化 CI 工作流
"""

import os
import sys
import io
import yaml
import json
from pathlib import Path
from typing import Dict, List, Set, Tuple
from dataclasses import dataclass, asdict
import argparse

# Fix Windows Unicode encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


@dataclass
class ModuleInfo:
    """模組信息"""
    name: str
    path: str
    priority: int
    critical: bool
    dockerfiles: List[str]
    depends_on: List[str]
    description: str = ""


class ModuleDetector:
    """自動檢測模組和 Dockerfile"""

    def __init__(self, root_dir: str = "."):
        self.root_dir = Path(root_dir)
        self.config_path = self.root_dir / ".github" / "modules.yaml"
        self.config = self._load_config()
        self.modules: Dict[str, ModuleInfo] = {}

    def _load_config(self) -> Dict:
        """載入模組配置文件"""
        if self.config_path.exists():
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        return {}

    def detect_modules(self) -> Dict[str, ModuleInfo]:
        """自動檢測所有模組"""
        print("🔍 Detecting modules...")

        if not self.config:
            print("⚠️  No modules.yaml found, scanning for Dockerfiles...")
            self._auto_scan_modules()
        else:
            self._load_configured_modules()

        return self.modules

    def _load_configured_modules(self):
        """從配置文件載入模組"""
        for module_name, module_cfg in self.config.get('modules', {}).items():
            module = ModuleInfo(
                name=module_name,
                path=module_cfg['path'],
                priority=module_cfg.get('priority', 999),
                critical=module_cfg.get('critical', False),
                dockerfiles=module_cfg.get('dockerfiles', []),
                depends_on=module_cfg.get('depends_on', []),
                description=module_cfg.get('description', '')
            )

            # 如果未指定 Dockerfile，嘗試自動檢測
            if not module.dockerfiles:
                detected = self._find_dockerfiles(module.path)
                module.dockerfiles = detected

            # 驗證 Dockerfile 存在
            if module.dockerfiles:
                self.modules[module_name] = module
            else:
                print(f"  ⚠️  {module_name}: No Dockerfile found at {module.path}")

    def _auto_scan_modules(self):
        """自動掃描所有 Dockerfile"""
        skip_patterns = self.config.get('ci_strategy', {}).get('skipPatterns', [])

        for dockerfile_path in self.root_dir.glob('**/Dockerfile*'):
            # 檢查是否跳過
            if any(dockerfile_path.as_posix().startswith(p) for p in skip_patterns):
                continue

            dir_path = dockerfile_path.parent.relative_to(self.root_dir)
            module_path = str(dir_path)

            # 跳過深層級的子模組 (> 2 levels)
            if module_path.count(os.sep) > 1:
                continue

            module_name = dir_path.name or "root"

            if module_name not in self.modules:
                self.modules[module_name] = ModuleInfo(
                    name=module_name,
                    path=module_path,
                    priority=999,
                    critical=False,
                    dockerfiles=[dockerfile_path.name],
                    depends_on=[],
                    description=f"Auto-detected: {module_path}"
                )

    def _find_dockerfiles(self, module_path: str) -> List[str]:
        """在指定路徑查找所有 Dockerfile"""
        dockerfiles = []
        module_dir = self.root_dir / module_path

        if not module_dir.exists():
            return []

        for file in module_dir.glob('Dockerfile*'):
            if file.is_file():
                dockerfiles.append(file.name)

        return dockerfiles

    def get_build_order(self) -> List[List[str]]:
        """根據優先級和依賴關係獲取構建順序"""
        # 按優先級分組
        priority_groups = {}
        for name, module in self.modules.items():
            priority = module.priority
            if priority not in priority_groups:
                priority_groups[priority] = []
            priority_groups[priority].append(name)

        # 按優先級排序返回
        build_order = []
        for priority in sorted(priority_groups.keys()):
            build_order.append(priority_groups[priority])

        return build_order

    def generate_ci_yaml(self, template: str = None) -> str:
        """生成 GitHub Actions CI YAML"""
        build_order = self.get_build_order()
        max_parallel = self.config.get('ci_strategy', {}).get('max_parallel_jobs', 3)

        # 生成 job 定義
        jobs = self._generate_jobs(build_order, max_parallel)

        ci_yaml = self._render_ci_template(jobs)
        return ci_yaml

    def _generate_jobs(self, build_order: List[List[str]], max_parallel: int) -> Dict:
        """生成 CI job 定義"""
        jobs = {}
        job_dependencies = []

        for stage_idx, stage_modules in enumerate(build_order):
            # 將同一優先級的模組分組成平行 job
            for batch_idx, i in enumerate(range(0, len(stage_modules), max_parallel)):
                batch = stage_modules[i:i+max_parallel]
                job_id = f"build_stage{stage_idx}_batch{batch_idx}"

                job_data = {
                    "modules": batch,
                    "needs": job_dependencies[-1:] if job_dependencies else [],
                    "matrix": {
                        "module": batch
                    }
                }

                jobs[job_id] = job_data

            if stage_modules:
                job_dependencies.append(f"build_stage{stage_idx}_batch0")

        return jobs

    def _render_ci_template(self, jobs: Dict) -> str:
        """渲染 CI YAML 模板"""
        template = """name: Docker Image CI (Modular)

on:
  push:
    branches: [ "main" ]
  pull_request:
    branches: [ "main" ]

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  detect-changes:
    runs-on: ubuntu-latest
    outputs:
      changed-modules: ${{ steps.detect.outputs.modules }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Detect changed modules
        id: detect
        run: |
          # 如果是 push to main，構建所有關鍵模組
          # 如果是 PR，只構建改動的模組
          if [ "${{ github.event_name }}" = "push" ]; then
            MODULE_LIST="alpamayo dashboard foxglove nanollm planning vlm ros1_ws_base ros1_ws_bridge ros1_ws_control"
          else
            # PR：檢測改動的文件
            MODULE_LIST=$(git diff --name-only origin/main HEAD | awk -F'/' '{print $1}' | sort -u | tr '\\n' ',' | sed 's/,$//')
          fi
          echo "modules=$MODULE_LIST" >> $GITHUB_OUTPUT

  setup:
    runs-on: ubuntu-latest
    steps:
      - name: Free Disk Space (Ubuntu)
        uses: jlumbroso/free-disk-space@main
        with:
          tool-cache: false
          android: true
          dotnet: true
          haskell: true
          large-packages: true
          docker-images: true
          swap-storage: true

      - name: Set up QEMU
        uses: docker/setup-qemu-action@v3

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

  # === TIER 1: 核心基礎模組 ===
  build-ros1_ws_base:
    needs: [setup, detect-changes]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          submodules: recursive

      - name: Build and lint ros1_ws_base
        run: |
          echo "🔨 Building ros1_ws_base..."
          for dockerfile in Dockerfile Dockerfile.l4t; do
            if [ -f "ros1_ws/base/$dockerfile" ]; then
              echo "  Linting $dockerfile..."
              docker run --rm -i hadolint/hadolint < "ros1_ws/base/$dockerfile" || true
              echo "  Building $dockerfile..."
              docker build ros1_ws/base -f "ros1_ws/base/$dockerfile" -t agx:ros1_ws_base
            fi
          done
          docker system prune -a -f

  # === TIER 2: ROS 구 ===
  build-ros1_ws_bridge:
    needs: [build-ros1_ws_base]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          submodules: recursive

      - name: Build and lint ros1_ws_bridge
        run: |
          echo "🔨 Building ros1_ws_bridge..."
          docker run --rm -i hadolint/hadolint < "ros1_ws/bridge/Dockerfile" || true
          docker build ros1_ws/bridge -f "ros1_ws/bridge/Dockerfile" -t agx:ros1_ws_bridge
          docker system prune -a -f

  build-ros1_ws_control:
    needs: [build-ros1_ws_base]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          submodules: recursive

      - name: Build and lint ros1_ws_control
        run: |
          echo "🔨 Building ros1_ws_control..."
          docker run --rm -i hadolint/hadolint < "ros1_ws/control/Dockerfile" || true
          docker build ros1_ws/control -f "ros1_ws/control/Dockerfile" -t agx:ros1_ws_control --build-arg BUILDKIT_INLINE_CACHE=1
          docker system prune -a -f

  # === TIER 3: 應用服務 ===
  build-applications:
    needs: [build-ros1_ws_control]
    runs-on: ubuntu-latest
    strategy:
      matrix:
        module: [vlm, planning, foxglove, nanollm, alpamayo]
    steps:
      - uses: actions/checkout@v4
        with:
          submodules: recursive

      - name: Build and lint ${{ matrix.module }}
        run: |
          MODULE=${{ matrix.module }}
          echo "🔨 Building $MODULE..."
          DOCKERFILE="$MODULE/Dockerfile"
          if [ -f "$DOCKERFILE" ]; then
            docker run --rm -i hadolint/hadolint < "$DOCKERFILE" || true
            docker build "$MODULE" -f "$DOCKERFILE" -t "agx:$MODULE"
          fi
          docker system prune -a -f

  build-dashboard:
    needs: [setup]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Build and lint dashboard
        run: |
          echo "🔨 Building dashboard..."
          docker run --rm -i hadolint/hadolint < "dashboard/Dockerfile" || true
          docker build dashboard -f "dashboard/Dockerfile" -t agx:dashboard
          docker system prune -a -f

  # 檢查點：所有構建完成
  verify-all-builds:
    needs: [build-applications, build-dashboard]
    runs-on: ubuntu-latest
    steps:
      - name: ✅ All builds completed successfully
        run: echo "All modules built successfully!"
"""
        return template


class CIGenerator:
    """CI 工作流生成器"""

    def __init__(self, detector: ModuleDetector):
        self.detector = detector
        self.modules = detector.detect_modules()

    def generate(self) -> str:
        """生成完整的 CI YAML"""
        return self.detector.generate_ci_yaml()

    def print_modules_summary(self):
        """列印模組摘要"""
        print("\n" + "=" * 60)
        print("📊 Detected Modules Summary")
        print("=" * 60)

        build_order = self.detector.get_build_order()

        for stage_idx, stage_modules in enumerate(build_order):
            print(f"\n📦 STAGE {stage_idx} (Priority: {stage_modules}):")
            for module_name in stage_modules:
                module = self.modules[module_name]
                critical = "⭐ CRITICAL" if module.critical else "⚪ Optional"
                print(f"  {module_name:25} {critical:15} {module.description}")
                if module.dockerfiles:
                    for dockerfile in module.dockerfiles:
                        print(f"    └─ {dockerfile}")
                if module.depends_on:
                    print(f"    └─ Depends on: {', '.join(module.depends_on)}")

        print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="AGX Modular CI Generator"
    )
    parser.add_argument(
        "--detect",
        action="store_true",
        help="Detect modules and print summary"
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Generate CI YAML workflow"
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output file for generated CI YAML",
        default=".github/workflows/docker-image-modular.yml"
    )
    parser.add_argument(
        "--root",
        "-r",
        help="Root directory of the project",
        default="."
    )

    args = parser.parse_args()

    # 創建檢測器
    detector = ModuleDetector(args.root)

    if args.detect or not (args.generate):
        # 列印模組摘要
        generator = CIGenerator(detector)
        generator.print_modules_summary()

    if args.generate:
        # 生成 CI YAML
        generator = CIGenerator(detector)
        ci_yaml = generator.generate()

        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(ci_yaml)

        print(f"\n✅ CI workflow generated: {args.output}")


if __name__ == "__main__":
    main()
