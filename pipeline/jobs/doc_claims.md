## Job: claims from one document

Read **one document** and report one field for one production unit.

- Unit: {{molecule_name}} (CAS {{cas}}, id `{{molecule_id}}`) at **{{site_name}}**, {{locality}}, {{country}},
  operated by {{operator_name}}. Unit id: `{{unit_id}}`.
- Field: **`{{field}}`**.
- Document: {{url}}. Its text has been saved as `document.txt` in the current directory: read that file
  (it is the text of the URL; PDFs may have OCR errors and tables may be flattened). Cite the URL above as the
  evidence `url`, and copy quotes from `document.txt` exactly.

Rules for this job:
- Use only this document. Don't search the web.
- Every claim uses `subject_ref: {"unit": "{{unit_id}}"}`.
- If the document states the field for **this unit**, emit the evidence and the claim (several values are fine
  if the document gives several, e.g. existing and after expansion, each with its own claim).
- If it doesn't (only a company total, an increment, a different product, a feedstock rate, or nothing), emit
  `not_found` and no claim for this field.
