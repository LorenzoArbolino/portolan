## Job: published coordinates for one site (J14)

Find coordinates **printed in a public document** for **{{site_name}}**, {{locality}}, {{country}} (site id
`{{site_id}}`, address: {{address}}). Good sources: environmental impact reports and permits (they usually print
latitude/longitude of the project site), mandated environmental disclosures, company "contact / locations"
pages, EU industrial-emissions (E-PRTR) facility pages. Search in: {{languages}}.

Emit a claim `field: "lat_lon"`, `subject_ref: {"site": "{{site_id}}"}`, `value` exactly as printed, with the
evidence quote containing the numbers. **Never** compute, estimate or read coordinates off a map, and don't
use geocoding services. If no document prints them: `not_found`.
