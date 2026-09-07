# Peer Review Report

**Manuscript:** Protocol: Verification of Slack and GitHub Integration for a Pre-Analysis Plan on the Effect of Sedentary Time on Type 2 Diabetes Incidence
**Target Journal:** Social Science & Medicine

---

## OVERALL ASSESSMENT

This protocol addresses a clinically relevant question (sedentary time and T2D incidence) and incorporates valuable open-science practices. However, the manuscript has substantial issues that must be addressed before submission. Most critically, the framing is misaligned with the target journal, the "novel" contribution (Slack/GitHub integration) is presented as a scientific contribution rather than a methodological tool, and the protocol lacks sufficient methodological detail for a registered report or protocol paper. The title itself signals a fundamental confusion: the *verification of Slack and GitHub integration* is not a research question—it is a quality-control procedure.

---

## 1. MANUSCRIPT NOVELTY, FOCUS, LOGIC, METHODS, CONSISTENCY

### Must-fix

**1.1 Title misrepresents the study's scientific contribution.**
The title foregrounds "Verification of Slack and GitHub Integration" as if this were the primary research contribution. This is a workflow detail, not a scientific finding. For *Social Science & Medicine*, the title should foreground the substantive epidemiological question.

**Fix:** Retitle to something like: "Sedentary Time and Type 2 Diabetes Incidence: A Protocol for a Systematic Review and Dose-Response Meta-Analysis with Transparent Computational Workflow" (or similar). The Slack/GitHub verification can be mentioned in the abstract or methods as a reproducibility feature, not in the title.

**1.2 The "novelty" claim is overstated and misdirected.**
The abstract claims "a novel verification of the computational reproducibility of the analysis pipeline using Slack and GitHub integration." Using GitHub for version control and Slack for notifications is standard practice in software development and increasingly common in data science. This is not novel. Moreover, the journal will not consider this a scientific contribution.

**Fix:** Reframe the contribution. The scientific novelty should be: (a) the dose-response meta-analysis specifically for T2D (if this has not been done—verify this claim), or (b) the pre-registered approach to handling measurement heterogeneity (self-reported vs. device-based). The Slack/GitHub integration should be described as a *transparency feature* demonstrating best practice, not as a novel contribution.

**1.3 The protocol lacks sufficient methodological detail for a protocol paper.**
The methods section is skeletal. Missing elements include:
- Specific search strategy (draft search strings, databases, date restrictions)
- Eligibility criteria (population characteristics, follow-up duration, minimum sample size)
- Risk of bias assessment tool and how it will be applied
- Specific dose-response modeling approach (e.g., restricted cubic splines, linear vs. non-linear testing)
- How heterogeneity will be quantified and explored
- How device-based vs. self-reported sedentary time will be harmonized
- How adjustment for physical activity will be handled (residual confounding is a major concern)
- How publication bias will be assessed
- Pre-specified sensitivity analyses

**Fix:** Substantially expand the methods section. Provide the full search strategy as an appendix or supplementary file. Specify the exact modeling framework (e.g., Greenland & Longnecker method or one-stage cubic splines). Detail how the exposure will be standardized across studies (e.g., MET-hours/week, hours/day). Specify the I² threshold for heterogeneity and pre-specified subgroup analyses with justification.

**1.4 The protocol does not address known methodological challenges in sedentary time research.**
The sedentary behavior field has well-documented issues: the "physical activity paradox," the strong correlation between sedentary time and total physical activity, reverse causality (early undiagnosed disease may reduce activity), and the measurement error in self-reported sedentary time. The protocol does not mention how these will be handled.

**Fix:** Add a section on "Methodological considerations and planned sensitivity analyses" that addresses: (a) exclusion of studies with <2 years follow-up to reduce reverse causality; (b) stratification by adjustment for physical activity (fully adjusted vs. not); (c) sensitivity analysis restricted to device-based measures; (d) assessment of the "activity paradox" by examining whether the association persists after adjustment for moderate-to-vigorous physical activity.

### High

**1.5 The target journal is not appropriate for this protocol.**
*Social Science & Medicine* publishes social science research on health. A dose-response meta-analysis of sedentary time and T2D is clinical/epidemiological, not social science. The protocol's emphasis on reproducibility workflows is more suited to journals like *BMJ Open*, *Systematic Reviews*, or *PLOS ONE*.

**Fix:** Reconsider the target journal. If the authors wish to target *Social Science & Medicine*, they need to substantially reframe the contribution around social determinants of sedentary behavior (e.g., occupational sitting, socioeconomic gradients in sedentary time) and the social-epidemiological implications. Otherwise, submit to a more appropriate venue.

**1.6 The protocol conflates two distinct objectives.**
The manuscript attempts to do two things: (a) pre-register a systematic review and meta-analysis, and (b) demonstrate a reproducible workflow. These have different audiences and different evaluation criteria. The current structure serves neither well.

**Fix:** Restructure the manuscript to make the systematic review the primary focus. The reproducibility workflow should be described in a dedicated section (e.g., "Transparency and Reproducibility") as a methodological feature, not as a co-equal objective.

---

## 2. STATISTICAL DESIGN AND UNCERTAINTY

### Must-fix

**2.1 The dose-response meta-analysis approach is underspecified.**
The abstract mentions "random-effects dose-response meta-analysis" but does not specify:
- The functional form to be tested (linear vs. non-linear)
- How non-linearity will be assessed (e.g., spline terms, fractional polynomials)
- How studies with categorical exposure data will be harmonized
- How the reference category will be defined across studies

**Fix:** Specify the planned analytical approach in detail. For example: "We will use a one-stage random-effects dose-response meta-analysis with restricted cubic splines (3 knots at the 10th, 50th, and 90th percentiles of the exposure distribution) to model the association between sedentary time and T2D incidence. Non-linearity will be tested using a Wald test comparing the spline model to a linear model. Studies reporting categorical exposure data will be harmonized by assigning the midpoint of each category; for open-ended categories, we will use the method described by [reference]."

**2.2 No plan for handling the correlation between sedentary time and physical activity is described.**
This is the single most important confounder in this literature. Studies that do not adjust for physical activity will produce inflated estimates. The protocol must specify how this will be handled.

**Fix:** Pre-specify that: (a) the primary analysis will be restricted to studies adjusting for at least one measure of physical activity; (b) a sensitivity analysis will compare estimates from studies with and without physical activity adjustment; (c) if sufficient studies exist, meta-regression will examine whether the sedentary-T2D association varies by the level of physical activity adjustment.

### High

**2.3 No specification of how heterogeneity will be quantified and explored.**
The protocol mentions "random-effects" but does not specify I² thresholds, prediction intervals, or pre-specified sources of heterogeneity.

**Fix:** Specify: "Heterogeneity will be quantified using the I² statistic and its 95% confidence interval. Prediction intervals will be reported for the pooled estimates. Pre-specified subgroup analyses will examine: (a) measurement method (device-based vs. self-reported), (b) adjustment for physical activity (yes/no), (c) follow-up duration (≥5 years vs. <5 years), (d) geographic region, and (e) sedentary time definition (total sitting, TV viewing, occupational sitting). Meta-regression will be used if ≥10 studies are available per subgroup."

**2.4 No mention of how the "dose" will be standardized.**
Sedentary time can be measured in hours/day, hours/week, or MET-hours/week. Different studies will use different metrics.

**Fix:** Specify the standardization approach. For example: "All sedentary time measures will be converted to hours per day. For studies reporting TV viewing, we will use the reported hours per day of TV viewing as a proxy. For studies reporting multiple sedentary behaviors, we will prioritize total sedentary time, followed by TV viewing, then occupational sitting."

**2.5 No plan for handling studies with multiple publications or overlapping cohorts.**
This is a common issue in meta-analyses of prospective cohorts.

**Fix:** Specify: "When multiple publications from the same cohort are identified, we will include the publication with the longest follow-up or the most complete adjustment for confounders. If publications from the same cohort report different exposure definitions, we will include the most comprehensive measure. A sensitivity analysis will exclude overlapping cohorts to assess the impact on pooled estimates."

---

## 3. FIGURES/TABLES SUPPORTING CLAIMS

### Must-fix

**3.1 No figures or tables are included.**
For a protocol paper, at least a PRISMA-P flow diagram and a summary table of planned analyses are expected.

**Fix:** Add:
- **Figure 1:** PRISMA-P flow diagram showing the planned study selection process
- **Table 1:** PICOS (Population, Intervention/Exposure, Comparison, Outcome, Study design) criteria
- **Table 2:** Summary of planned analyses, including primary analysis, subgroup analyses, sensitivity analyses, and the specific statistical methods for each

### High

**3.2 No figure illustrating the planned dose-response modeling approach.**
Given the complexity of dose-response meta-analysis, a figure showing the planned spline modeling approach would help readers understand the analytical plan.

**Fix:** Add a figure (conceptual, not data-based) showing: (a) how study-specific dose-response curves will be extracted, (b) how they will be pooled, and (c) how non-linearity will be tested.

---

## 4. REPRODUCIBILITY AND DATA PROVENANCE

### Must-fix

**4.1 The reproducibility claims are not verifiable from the protocol.**
The protocol claims that "all analysis code will be version-controlled on GitHub, with automated notifications via Slack" but does not provide:
- The GitHub repository URL (or a statement that it will be made public upon acceptance)
- The specific tools for continuous integration (e.g., GitHub Actions, Travis CI)
- How the analysis environment will be containerized (e.g., Docker, Conda)
- How data will be shared (raw data from primary studies cannot be shared, but extracted data can be)

**Fix:** Provide a "Reproducibility" section that specifies: (a) the GitHub repository will be made public upon acceptance; (b) the analysis will use R (version specified) with the `renv` package for dependency management; (c) a Docker container will be provided for full environment reproducibility; (d) the extracted dataset will be deposited in a public repository (e.g., Zenodo, OSF) with a DOI; (e) the Slack integration is for internal project management and does not constitute a reproducibility feature per se—what matters is the version-controlled code and data.

**4.2 The "verification" of reproducibility is not described.**
The title claims "verification" of the integration, but no verification process is described. What does verification mean here? That the Slack notifications fire correctly? That the GitHub repository is properly configured? This is not a scientific verification.

**Fix:** Either remove the "verification" framing entirely, or if the authors wish to evaluate their workflow, describe a specific process: e.g., "Two independent analysts will attempt to reproduce the final analysis from the version-controlled code and extracted data. Successful reproduction will be defined as identical point estimates and confidence intervals to two decimal places." This would constitute a meaningful reproducibility verification.

### High

**4.3 No data management plan is described.**
The protocol does not specify how extracted data will be managed, quality-checked, or stored.

**Fix:** Add a data management section specifying: (a) data extraction will be performed in duplicate using a piloted extraction form; (b) discrepancies will be resolved by consensus or third reviewer; (c) extracted data will be stored in a structured format (CSV or RDS) with a data dictionary; (d) data will be version-controlled alongside the analysis code.

---

## 5. STRENGTH OF CLAIMS VS. EVIDENCE

### Must-fix

**5.1 The conclusion overstates what a protocol can claim.**
The abstract concludes: "This protocol, with transparent version control, will provide robust evidence on sedentary time and T2D risk." This is an overstatement. A protocol does not provide evidence; it describes a plan to generate evidence. Moreover, the claim that the evidence will be "robust" is premature.

**Fix:** Revise the conclusion to: "This pre-registered protocol describes a systematic review and dose-response meta-analysis that will quantify the association between sedentary time and T2D incidence, with pre-specified subgroup and sensitivity analyses to address key sources of heterogeneity and bias. The transparent computational workflow will facilitate reproducibility and updating of the evidence."

**5.2 The claim that the Slack/GitHub integration "demonstrates a reproducible workflow for future social epidemiology studies" is not supported.**
A workflow that uses Slack and GitHub is reproducible only if the code, data, and environment are publicly available and the analysis can be independently rerun. The protocol does not yet demonstrate this.

**Fix:** Remove this claim or substantiate it by describing the specific reproducibility features (public repository, containerized environment, deposited data) and how they will be verified.

### High

**5.3 The protocol does not acknowledge the limitations of the planned approach.**
Key limitations that should be acknowledged:
- Residual confounding (sedentary time is correlated with many lifestyle factors)
- Measurement error in self-reported sedentary time
- Potential publication bias
- Inability to establish causality from observational data

**Fix:** Add a "Limitations" section that acknowledges these issues and describes how the planned analyses address (but cannot eliminate) them.

---

## ADDITIONAL ISSUES

### Medium

**5.4 The abstract is too brief and lacks key elements.**
For a protocol paper, the abstract should include: the research question in PICO format, the planned search sources and dates, the primary and secondary outcomes, the planned statistical methods, and the registration details (PROSPERO or OSF).

**Fix:** Expand the abstract to include these elements. Note that the protocol should be registered (e.g., PROSPERO) before submission—this is not mentioned.

**5.5 No timeline or project management plan is provided.**
Protocol papers typically include an estimated timeline for completion.

**Fix:** Add a brief timeline (e.g., "Search completion: [month/year]; Data extraction: [months]; Analysis: [months]; Expected completion: [month/year]").

**5.6 The protocol does not specify how the certainty of evidence will be assessed.**
For a systematic review and meta-analysis, GRADE (Grading of Recommendations, Assessment, Development, and Evaluations) or a similar framework should be used.

**Fix:** Specify: "The certainty of evidence for the primary outcome will be assessed using the GRADE framework, with ratings downgraded for risk of bias, inconsistency, indirectness, imprecision, and publication bias."

### Optional

**5.7 The protocol does not mention patient and public involvement.**
Some journals and reviewers expect this.

**Fix:** Add a brief statement: "Patient and public involvement: This is a systematic review of published literature; no patients will be involved in the conduct of this research. The research question was informed by public health priorities regarding sedentary behavior and chronic disease prevention."

**5.8 The protocol does not specify funding sources or conflicts of interest.**
These should be declared.

**Fix:** Add declarations of funding and conflicts of interest.

---

## SUMMARY OF PRIORITY ISSUES

| Priority | Issue | Location |
|----------|-------|----------|
| **Must-fix** | Title misrepresents scientific contribution | Title |
| **Must-fix** | Novelty claim overstated and misdirected | Abstract, throughout |
| **Must-fix** | Insufficient methodological detail | Methods |
| **Must-fix** | No handling of physical activity confounding | Methods |
| **Must-fix** | Dose-response approach underspecified | Methods |
| **Must-fix** | No figures/tables | Entire manuscript |
| **Must-fix** | Reproducibility claims not verifiable | Methods |
| **Must-fix** | Conclusion overstates claims | Abstract, Conclusion |
| **High** | Target journal mismatch | Submission |
| **High** | No heterogeneity quantification plan | Methods |
| **High** | No standardization of exposure metric | Methods |
| **High** | No handling of overlapping cohorts | Methods |
| **High** | No data management plan | Methods |
| **High** | Limitations not acknowledged | Throughout |
| **Medium** | Abstract too brief | Abstract |
| **Medium** | No timeline | Methods |
| **Medium** | No GRADE assessment | Methods |
| **Optional** | No PPI statement | Throughout |
| **Optional** | No funding/COI declarations | Throughout |

---

## RECOMMENDATION

**Major revision required before submission.** The authors should:

1. **Reframe the manuscript** around the substantive epidemiological question (sedentary time and T2D), treating the computational workflow as a transparency feature rather than the primary contribution.
2. **Substantially expand the methods section** to meet the standards of a protocol paper for a systematic review and meta-analysis.
3. **Reconsider the target journal** or reframe the contribution for *Social Science & Medicine*.
4. **Add all required elements**: PRISMA-P flow diagram, PICOS table, planned analyses table, data management plan, limitations section, and registration details.
5. **Revise the title and abstract** to accurately reflect the scientific contribution.

The substantive question is important, and the commitment to transparency is commendable. However, in its current form, the manuscript does not meet the standards for a protocol paper in a peer-reviewed journal.