from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config import settings
from models import AgentTemplateConfig, PatientProfile, SimulationRunRecord

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None


class LocalDataStore:
    """基于本地文件的测试资产与运行结果仓库。"""

    def __init__(self):
        self.patient_dir = settings.PATIENT_PROFILES_DIR
        self.template_dir = settings.AGENT_TEMPLATES_DIR
        self.run_dir = settings.TEST_RUNS_DIR

        for path in (self.patient_dir, self.template_dir, self.run_dir):
            path.mkdir(parents=True, exist_ok=True)

    def list_patient_profiles(self) -> list[PatientProfile]:
        return [PatientProfile.model_validate(item) for item in self._load_documents(self.patient_dir)]

    def list_agent_templates(self) -> list[AgentTemplateConfig]:
        return [AgentTemplateConfig.model_validate(item) for item in self._load_documents(self.template_dir)]

    def get_patient_profile(self, profile_id: str) -> PatientProfile:
        for item in self.list_patient_profiles():
            if item.id == profile_id:
                return item
        raise KeyError(f"未找到患者画像: {profile_id}")

    def get_agent_template(self, template_id: str) -> AgentTemplateConfig:
        for item in self.list_agent_templates():
            if item.id == template_id:
                return item
        raise KeyError(f"未找到 Agent 模板: {template_id}")

    def save_run(self, run_record: SimulationRunRecord) -> Path:
        output_path = self.run_dir / f"{run_record.run_id}.json"
        output_path.write_text(
            json.dumps(run_record.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return output_path

    def _load_documents(self, directory: Path) -> list[dict[str, Any]]:
        documents = []
        for path in sorted(directory.iterdir()):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".json", ".yaml", ".yml"}:
                continue
            documents.append(self._read_document(path))
        return documents

    @staticmethod
    def _read_document(path: Path) -> dict[str, Any]:
        raw_text = path.read_text(encoding="utf-8")
        suffix = path.suffix.lower()

        if suffix == ".json":
            return json.loads(raw_text)

        if yaml is None:
            raise RuntimeError(f"文件 {path.name} 是 YAML，但当前环境未安装 PyYAML。")

        return yaml.safe_load(raw_text)
