"""
筛选配置示例 - 针对不同疾病和研究主题的配置

使用方法：
在 scripts/cli/screening_llm_batch.py 中传入 screening_config 参数

示例：
    from screening_configs import CONFIG_COVID_VARIANTS
    screen_papers_batch(papers, research_question, llm, screening_config=CONFIG_COVID_VARIANTS)
"""

# ========== Parmeter: Serial Interval 研究 ==========
P10 = {
    "research_question": "What are the serial interval and generation time of SARS-CoV-2 variants such as Omicron and Delta?",
    "disease_focus": "(SARS-CoV-2 OR COVID-19) AND (variant OR mutation OR lineage OR amino acid substitution)",
    "disease_exclude": "studies that focus solely on the wild-type virus without variant comparison",
    "transmission_focus": "studies that report or estimate serial interval or generation time (including studies where these parameters are reported in the full text but not explicitly mentioned in the title or abstract)",
    "transmission_exclude": "studies that do not report or estimate serial interval or generation time in the full text",
}


P11 = {
    "research_question": "What are the serial interval and generation time of SARS-CoV-2 estimated from contact tracing or household transmission studies?",
    "disease_focus": '(COVID-19 OR SARS-CoV-2 OR 2019-nCoV OR "coronavirus disease 2019" OR "severe acute respiratory syndrome coronavirus 2")',
    "disease_exclude": "none",
    "transmission_focus": "(serial interval* OR generation time* OR generation interval*)",
    "transmission_exclude": "studies that do not report or estimate serial interval or generation time",
}

P12 = {
    "research_question": "What are the serial interval and generation time of COVID-19?",
    "disease_focus": "(COVID-19 OR SARS-CoV-2 OR novel coronavirus)",
    "disease_exclude": "none",
    "transmission_focus": "(serial interval OR generation time OR generation interval)",
    "transmission_exclude": "studies that do not report or estimate serial interval or generation time",
}

P13 = {
    "research_question": "What are the serial interval and generation time of COVID-19?",
    "disease_focus": "(COVID-19 OR SARS-CoV-2 OR coronavirus OR 2019-nCoV OR SARS-CoV)",
    "disease_exclude": "none",
    "transmission_focus": "(serial interval OR generation interval OR generation time OR serial distribution)",
    "transmission_exclude": "studies that do not report or estimate serial interval or generation time",
}

P14 = {
    "research_question": "What is the serial interval of COVID-19?",
    "disease_focus": "(COVID-19 OR 2019-nCoV OR coronavirus)",
    "disease_exclude": "none",
    "transmission_focus": "(serial interval)",
    "transmission_exclude": "studies that do not report or estimate serial interval",
}

# ========== Parmeter: Basic Reproduction Number 研究 ==========
P7 = {
    "research_question": "What is the basic reproduction number (R0) of COVID-19?",
    "disease_focus": "(COVID-19 OR SARS-CoV-2 OR 2019-nCoV OR coronavirus)",
    "disease_exclude": "none",
    "transmission_focus": "(basic reproduction number OR basic reproductive number OR R0 OR R naught OR reproduction number)",
    "transmission_exclude": "none",
}

P8 = {
    "research_question": "What is the basic reproduction number (R0) of COVID-19?",
    "disease_focus": "(2019 novel coronavirus OR COVID-19 OR SARS-CoV-2)",
    "disease_exclude": "none",
    "transmission_focus": "(basic reproduction number OR basic reproductive number OR R0 OR R naught OR reproduction number)",
    "transmission_exclude": "none",
}

P15 = {
    "research_question": "What is the reproduction/reproductive number (R0) of COVID-19?",
    "disease_focus": '(Coronavirus OR "Corona virus" OR COVID-19 OR SARS-CoV-2 OR n2019-CoV OR "novel coronavirus")',
    "disease_exclude": "none",
    "transmission_focus": '(reproductive number OR reproduction number OR R0 OR "R naught")',
    "transmission_exclude": "none",
}

P16 = {
    "research_question": "What is the basic reproduction number (R0) of COVID-19?",
    "disease_focus": "(novel coronavirus OR SARS-CoV-2 OR 2019 novel coronavirus disease OR COVID-19)",
    "disease_exclude": "none",
    "transmission_focus": "(basic reproduction number OR R0 OR R naught OR reproduction number)",
    "transmission_exclude": "none",
}

P17 = {
    "research_question": "What is the basic reproduction number (R0) of COVID-19?",
    "disease_focus": "(COVID-19)",
    "disease_exclude": "none",
    "transmission_focus": "(basic reproduction number OR R0)",
    "transmission_exclude": "none",
}


# ========== Parmeter: Fatality Rate 研究 ==========
P4 = {
    "research_question": "What are the fatality and severity outcomes of SARS-CoV-2 infection?",
    "disease_focus": "(COVID-19 OR COVID19 OR SARS-CoV-2 OR SARS-COV-2 OR 2019-nCoV OR coronavirus OR coronavirus disease 2019)",
    "disease_exclude": "none",
    "transmission_focus": "(mortality OR fatality OR death OR died OR ICU OR intensive care OR intensive care unit OR invasive mechanical ventilation OR mechanical ventilation OR ventilation OR clinical characteristic*)",
    "transmission_exclude": "studies that do not report mortality, fatality, ICU admission, or invasive mechanical ventilation outcomes",
}

P5 = {
    "research_question": "What are the fatality rates of SARS-CoV-2 inferred from seroprevalence or antibody studies?",
    "disease_focus": "(COVID-19 OR COVID19 OR SARS-CoV-2 OR SARS-COV-2 OR 2019-nCoV OR coronavirus)",
    "disease_exclude": "none",
    "transmission_focus": "(seroprevalence OR antibodies)",
    "transmission_exclude": "none",
}

P6 = {
    "research_question": "What is the mortality or case fatality rate of COVID-19?",
    "disease_focus": "(COVID-19 OR COVID 19 OR COVID-2019 OR 2019-nCoV OR 2019nCoV OR SARS-CoV-2 OR severe acute respiratory syndrome coronavirus 2 OR ((Wuhan AND coronavirus)))",
    "disease_exclude": "none",
    "transmission_focus": "(mortality OR (case AND fatality AND rate) OR case fatality rate)",
    "transmission_exclude": "none",
}

P9 = {
    "research_question": "What is the infection fatality rate of COVID-19 estimated from seroprevalence studies?",
    "disease_focus": "(COVID-19 OR COVID-2019 OR COVID 19 OR 2019-nCoV OR 2019nCoV OR SARS-CoV-2 OR severe acute respiratory syndrome coronavirus 2)",
    "disease_exclude": "none",
    "transmission_focus": "(seroprevalence OR infection fatality rate)",
    "transmission_exclude": "none",
}
