"""配置管理模块

从 YAML 配置文件加载和验证运行时配置。
"""

import os
from pathlib import Path
from typing import Dict, Any, List, Optional
import yaml
from dataclasses import dataclass, field


@dataclass
class PubMedConfig:
    """PubMed 配置"""

    max_results: int = 500
    retmax_per_fetch: int = 500
    include_medline_only: bool = True
    year_filter: Optional[str] = None


@dataclass
class KeywordGenerationConfig:
    """关键词生成配置"""

    max_iterations: int = 3
    enable_domain_analysis: bool = True
    include_wildcards: bool = True
    category_limits: Dict[str, int] = field(
        default_factory=lambda: {
            "primary_keywords": 20,
            "synonyms": 30,
            "related_terms": 25,
            "domain_terms": 20,
            "outcome_terms": 20,
            "design_terms": 15,
            "population_terms": 15,
        }
    )


@dataclass
class QueryGenerationConfig:
    """布尔查询生成配置"""

    max_queries_per_provider: int = 12
    use_llm_queries: bool = True
    fallback_to_rules: bool = True
    llm_max_retries: int = 2
    include_single_terms: bool = False
    min_terms_per_query: int = 2
    max_terms_per_query: int = 15


@dataclass
class ScreeningConfig:
    """筛选配置"""

    enable_autoscreen: bool = True
    autoscreen_batch_size: int = 10
    study_design_priority: List[str] = field(
        default_factory=lambda: [
            "meta_analysis",
            "systematic_review",
            "cohort",
            "case_control",
            "randomized_controlled_trial",
            "cross_sectional",
        ]
    )
    exclude_types: List[str] = field(
        default_factory=lambda: ["editorial", "commentary", "letter", "case_report"]
    )


@dataclass
class ScopingConfig:
    """Scoping search 配置"""

    enabled: bool = False
    providers: List[str] = field(default_factory=lambda: ["tavily"])
    max_results: int = 5
    max_items: int = 8
    max_chars: int = 1600


@dataclass
class OutputConfig:
    """输出配置"""

    export_formats: List[str] = field(default_factory=lambda: ["csv", "json"])
    include_prisma_diagram: bool = True
    save_intermediate_results: bool = True
    csv_columns: List[str] = field(
        default_factory=lambda: [
            "id",
            "title",
            "authors",
            "year",
            "abstract",
            "journal",
            "doi",
            "source",
            "decision",
            "reason",
            "study_design",
        ]
    )


@dataclass
class PerformanceConfig:
    """性能配置"""

    parallel_retrieval: bool = True
    api_rate_limit_delay: float = 0.34
    max_concurrent_requests: int = 3
    warn_if_results_exceed: int = 10000


@dataclass
class LoggingConfig:
    """日志配置"""

    level: str = "INFO"
    log_llm_calls: bool = True
    log_api_responses: bool = False


@dataclass
class PipelineConfig:
    """完整的流水线配置"""

    default_providers: List[str] = field(default_factory=lambda: ["pubmed"])
    pubmed: PubMedConfig = field(default_factory=PubMedConfig)
    keyword_generation: KeywordGenerationConfig = field(
        default_factory=KeywordGenerationConfig
    )
    query_generation: QueryGenerationConfig = field(
        default_factory=QueryGenerationConfig
    )
    screening: ScreeningConfig = field(default_factory=ScreeningConfig)
    scoping: ScopingConfig = field(default_factory=ScopingConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    performance: PerformanceConfig = field(default_factory=PerformanceConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @classmethod
    def from_yaml(cls, yaml_path: str) -> "PipelineConfig":
        """从 YAML 文件加载配置"""
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return cls(
            default_providers=data.get("default_providers", ["pubmed"]),
            pubmed=PubMedConfig(**data.get("pubmed", {})),
            keyword_generation=KeywordGenerationConfig(
                **data.get("keyword_generation", {})
            ),
            query_generation=QueryGenerationConfig(**data.get("query_generation", {})),
            screening=ScreeningConfig(**data.get("screening", {})),
            scoping=ScopingConfig(**data.get("scoping", {})),
            output=OutputConfig(**data.get("output", {})),
            performance=PerformanceConfig(**data.get("performance", {})),
            logging=LoggingConfig(**data.get("logging", {})),
        )

    @classmethod
    def load_default(cls) -> "PipelineConfig":
        """加载默认配置"""
        config_dir = Path(__file__).parent.parent / "configs"
        default_config_path = config_dir / "pipeline_config.yaml"

        if default_config_path.exists():
            return cls.from_yaml(str(default_config_path))
        else:
            return cls()  # 返回硬编码的默认值


# 全局配置实例
_config: Optional[PipelineConfig] = None


def get_config() -> PipelineConfig:
    """获取全局配置实例"""
    global _config
    if _config is None:
        _config = PipelineConfig.load_default()
    return _config


def set_config(config: PipelineConfig):
    """设置全局配置实例"""
    global _config
    _config = config


def reload_config(yaml_path: Optional[str] = None):
    """重新加载配置"""
    global _config
    if yaml_path:
        _config = PipelineConfig.from_yaml(yaml_path)
    else:
        _config = PipelineConfig.load_default()
