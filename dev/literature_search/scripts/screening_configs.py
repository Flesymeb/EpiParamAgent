"""
筛选配置示例 - 针对不同疾病和研究主题的配置

使用方法：
在screening_llm_batch.py中传入screening_config参数

示例：
    from screening_configs import CONFIG_COVID_VARIANTS
    screen_papers_batch(papers, research_question, llm, screening_config=CONFIG_COVID_VARIANTS)
"""

# ========== Search V1: Serial Interval 研究 ==========
CONFIG_SERIAL_INTERVAL = {
    "research_question": "What are the serial interval and generation time of SARS-CoV-2?",
    "disease_focus": "`COVID-19` OR `coronavirus` OR `2019 nCoV` OR `SARS CoV 2` OR `SARS-CoV-2 `OR `SARS-CoV` OR `SARS CoV` OR `2019 CoV` OR `Pneumonia`",
    "disease_exclude": "none",
    "transmission_focus": "metrics include serial interval (`serial interval` OR `generation interval` OR `generation time` OR `serial distribution`)",
    "transmission_exclude": "studies that do not report or estimate serial interval or generation time",
}

# ========== Search V2: COVID-19 变异株传播研究 ==========
CONFIG_COVID_VARIANTS = {
    "research_question": "What are the reproduction numbers of different SARS-CoV-2 variants?",
    "disease_focus": "(SARS-CoV-2 OR COVID-19 OR 2019-nCoV OR coronavirus) AND its (variant OR mutation OR lineage OR amino acid substitution)",
    "disease_exclude": "studies that focus solely on wild-type only without variant comparison",
    "transmission_focus": "transmission metrics **related to variants** (reproduct* number OR reproduct* ratio OR reproduct* rate)",
    "transmission_exclude": "papers that do not report these metrics",
}

# ========== Search V3: Superspreading 研究 ==========
# ========== Search V3: Superspreading 研究 ==========
CONFIG_SUPERSPREADING = {
    "research_question": (
        "What are the superspreading patterns and heterogeneity in SARS-CoV-2 transmission, "
        "quantified by negative-binomial offspring dispersion k or clearly convertible equivalents?"
    ),
    "disease_focus": (
        "(COVID-19 OR COVID19 OR SARS-CoV-2 OR SARS-COV-2 OR 2019-nCoV OR Coronavirus 2019 "
        "OR 2019 coronavirus OR coronavirus Wuhan OR pneumonia Wuhan)"
    ),
    "disease_exclude": "none",
    "transmission_focus": (
        "Include studies that quantify transmission heterogeneity (superspreading/overdispersion) "
        "using a negative-binomial offspring distribution (Lloyd-Smith style) or equivalent branching-process / "
        "cluster-size / secondary-infections-per-case frameworks, and report at least one of: "
        "(1) dispersion parameter k (or 1/k; or NB overdispersion explicitly defined), or "
        "(2) a 20/80 rule metric (e.g., p or p_h: fraction of cases responsible for 80% of transmissions) "
        "together with a reproduction number R so that k can be inferred under a negative-binomial offspring model."
    ),
    "transmission_exclude": (
        "Exclude studies that only discuss superspreading qualitatively without estimating a parameter. "
        "Exclude studies that quantify heterogeneity only indirectly via infectiousness-rate variance (beta variance), "
        "variance in early growth rates across regions/subpopulations, Gini/inequality metrics, "
        "or other proxies that do not estimate NB-offspring k and are not clearly convertible to k."
    ),
}

# "transmission_focus": "studies that report or estimate transmission heterogeneity metrics (superspreading OR superspreader OR super-spreading OR super-spreader OR overdispersion OR dispersion parameter OR k parameter OR negative-binomial OR offspring distribution OR transmission heterogeneity OR individual variation in transmission OR 80/20 rule OR 20/80 rule)",
# "transmission_exclude": "studies that only discuss general transmission without quantifying heterogeneity or superspreading potential",


# ========== 流感传播研究 ==========
CONFIG_INFLUENZA_TRANSMISSION = {
    "research_question": "What are the transmission dynamics of influenza?",
    "disease_focus": "influenza (seasonal influenza OR pandemic influenza OR H1N1 OR H3N2 OR influenza A OR influenza B)",
    "disease_exclude": "studies on other respiratory diseases without influenza data",
    "transmission_focus": "transmission metrics (e.g., reproduction number, serial interval, attack rate, transmission probability, household transmission)",
    "transmission_exclude": "studies that only discuss clinical outcomes, severity, or vaccine effectiveness without transmission quantification",
}

# ========== 麻疹传播研究 ==========
CONFIG_MEASLES_TRANSMISSION = {
    "research_question": "What are the transmission dynamics of measles?",
    "disease_focus": "measles (rubeola OR morbillivirus)",
    "disease_exclude": "studies on other vaccine-preventable diseases without measles data",
    "transmission_focus": "transmission dynamics (e.g., reproduction number, serial interval, attack rate, contact rates, transmission in healthcare/school settings)",
    "transmission_exclude": "studies solely on vaccine coverage, immunogenicity, or clinical management without transmission data",
}

# ========== 埃博拉传播研究 ==========
CONFIG_EBOLA_TRANSMISSION = {
    "research_question": "What are the transmission patterns of Ebola virus disease?",
    "disease_focus": "Ebola virus disease (EVD OR Ebola hemorrhagic fever OR filovirus)",
    "disease_exclude": "studies on other hemorrhagic fevers without Ebola data",
    "transmission_focus": "transmission patterns (e.g., reproduction number, serial interval, transmission chains, household/healthcare transmission, funeral-related transmission)",
    "transmission_exclude": "studies solely on clinical trials, case management, or laboratory diagnostics without transmission analysis",
}

# ========== 结核病传播研究 ==========
CONFIG_TB_TRANSMISSION = {
    "research_question": "What are the transmission dynamics of tuberculosis?",
    "disease_focus": "tuberculosis (TB OR Mycobacterium tuberculosis OR drug-resistant TB OR MDR-TB OR XDR-TB)",
    "disease_exclude": "studies on other mycobacterial diseases without tuberculosis data",
    "transmission_focus": "transmission dynamics (e.g., reproduction number, transmission rate, household contacts, clustering analysis, molecular epidemiology)",
    "transmission_exclude": "studies solely on treatment outcomes, drug resistance testing, or clinical management without transmission analysis",
}

# ========== 通用传染病传播研究（最宽松） ==========
CONFIG_GENERIC_INFECTIOUS_DISEASE = {
    "research_question": "What are the transmission dynamics of this infectious disease?",
    "disease_focus": "any infectious disease with human-to-human transmission potential",
    "disease_exclude": "purely animal diseases with no zoonotic potential or human cases",
    "transmission_focus": "transmission-related metrics or epidemiological parameters (e.g., reproduction number, incidence, attack rate, contact patterns, transmission risk factors)",
    "transmission_exclude": "studies solely on clinical management, diagnostics, or treatment without epidemiological transmission data",
}

# ========== 疾病暴发调查（Outbreak investigation） ==========
CONFIG_OUTBREAK_INVESTIGATION = {
    "research_question": "What are the characteristics and transmission patterns of this disease outbreak?",
    "disease_focus": "any infectious disease outbreak or epidemic/pandemic",
    "disease_exclude": "endemic disease surveillance without outbreak context",
    "transmission_focus": "outbreak characteristics (e.g., attack rate, case counts, transmission chains, source identification, outbreak duration, control measures effectiveness)",
    "transmission_exclude": "routine surveillance reports without outbreak investigation or transmission analysis",
}
