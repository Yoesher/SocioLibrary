# Social science research workspace

SocioLibrary supports multiple social science research traditions while keeping the application name **SocioLibrary**. The application UI remains Chinese.

The search page offers 11 research lenses: general social science; education; economics and labor; politics and public administration; psychology and behavior; sociology and demography; communication; human geography; history; anthropology; and law and society.

A lens changes question examples and evidence-review instructions. It never filters out other disciplines, changes PDF access, expands the semantic pilot, changes an AI credential, or subscribes to a journal. Existing multilingual vectors remain usable. Offline terminology expansion covers common concepts and methods across these areas; it is a bounded glossary, not arbitrary sentence translation.

The research route connects local search, source selection, evidence review, comparison and saved notes or graphs. Three new reading tasks support methods and argument review, evidence and disagreement mapping, and a literature-review outline. Preparing a task makes no model request. The existing 1–8 source selection, exact preview, explicit consent and single-use confirmation still apply. Changing a lens invalidates a prepared AI request in both the interface and server.

Prompts distinguish quantitative, qualitative, mixed, historical, normative and theoretical work. They do not require samples or statistical results from theoretical arguments, turn association into causation, or infer an entire field's research gap from a few passages. Comparison matrices retain their six internal fields and existing content.

Each specialist lens offers one journal as a configuration starting point. The button only prefills its name, Crossref provider and ISSN. The user must validate and save before subscribing. Ten journal identities were checked against the Crossref journal endpoint on 2026-11-13; this does not establish complete or timely coverage, or full-text access. The [Chinese guide](../social-science.md) includes the source links and ISSNs.

For a public demonstration without private papers, run `python scripts/create_social_science_demo.py --directory ./demo-social-science` from the repository, then launch `python -m sociolit.desktop --data-dir ./demo-social-science`. Creation requires a new empty folder. All ten documents and twenty PDF pages are original synthetic examples, explicitly labeled as demonstrations rather than real publications or empirical findings. They do not prove research effectiveness.
