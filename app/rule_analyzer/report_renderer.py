"""
Renders a structured FinalReport into consistent Markdown, EVERY time,
regardless of how the LLM phrased anything internally -- this is the
whole point of structuring the report first. Kept SEPARATE from the
schema and from investigation_graph.py, same modularity discipline as
aql_prompt_templates.py: template content reviewable/tunable on its
own.
"""
from __future__ import annotations

from jinja2 import Environment

from app.rule_analyzer.final_report_schema import FinalReport

# trim_blocks/lstrip_blocks: Jinja's default whitespace handling around
# {% for %}/{% endfor %} leaves noticeable extra blank lines -- these
# strip that, and the template below adds blank lines back explicitly
# ONLY where readability actually needs them, giving full control
# over spacing instead of fighting Jinja's defaults either way.
_env = Environment(trim_blocks=True, lstrip_blocks=True)

_REPORT_TEMPLATE = _env.from_string(
    """\
# Rule Investigation Report

## What This Rule Detects
{{ report.detection_intent }}

## Structural Assessment
{{ report.structural_summary }}

## Most Likely Root Causes
{% for cause in report.root_causes %}
### {{ loop.index }}. {{ cause.cause }} (Confidence: {{ cause.confidence|upper }})

**Evidence:**
{% for e in cause.evidence %}
- {{ e }}
{% endfor %}

**Next steps:**
{% for step in cause.next_steps %}
- {{ step }}
{% endfor %}
{% if not loop.last %}

{% endif %}
{% endfor %}
## Overall Recommendation
{{ report.overall_recommendation }}
{% if report.additional_findings %}

## Additional Findings / Potential New Rule Opportunities
{% for finding in report.additional_findings %}
### {{ loop.index }}. {{ finding.observation }}

**Evidence:**
{% for e in finding.evidence %}
- {{ e }}
{% endfor %}

**Suggested next step:** {{ finding.suggested_next_step }}
{% if not loop.last %}

{% endif %}
{% endfor %}
{% endif %}
"""
)


def render_report(report: FinalReport) -> str:
    return _REPORT_TEMPLATE.render(report=report).rstrip() + "\n"