"""Recorded-style responses of the public APIs used by the gap-search tests."""

ABSTRACT = (
    "STXBP1 encephalopathy and Dravet syndrome share early-onset seizures. "
    "Here we report that Dravet syndrome is caused by variants in STXBP1 in a subset of patients."
)
QUOTE = "Dravet syndrome is caused by variants in STXBP1 in a subset of patients"

ESEARCH = {"esearchresult": {"count": "1", "idlist": ["40000001"]}}

EFETCH = f"""<?xml version="1.0" ?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID Version="1">40000001</PMID>
      <Article>
        <ArticleTitle>Synthetic overlap of STXBP1 and Dravet syndrome.</ArticleTitle>
        <Abstract><AbstractText Label="RESULTS">{ABSTRACT}</AbstractText></Abstract>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
""".encode()

CTGOV = {
    "studies": [
        {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT09999999",
                    "briefTitle": "Natural history of STXBP1 and Dravet syndrome",
                },
                "descriptionModule": {
                    "briefSummary": "A natural history study enrolling children with STXBP1 "
                    "encephalopathy or Dravet syndrome."
                },
                "conditionsModule": {"conditions": ["Dravet Syndrome", "STXBP1 Encephalopathy"]},
            }
        },
        {"protocolSection": {"identificationModule": {"nctId": "not-an-id"}}},
    ]
}

PAGE_HTML = """<!doctype html><html><head><title>t</title><script>var secret=1;</script></head>
<body><nav>menu</nav><h1>Review</h1><p>Several reports suggest that Dravet syndrome
is caused by variants in STXBP1 in rare cases.</p></body></html>"""
PAGE_QUOTE = "Dravet syndrome is caused by variants in STXBP1 in rare cases"
