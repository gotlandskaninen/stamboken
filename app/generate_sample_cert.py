"""Render a signed sample of the production certificate template (Template A).

Dev utility for template tweaking — no stack or DB needed. Run inside the
api container: docker compose exec api python3 generate_sample_cert.py
Output: /tmp/cert_sample.pdf (signed with the committed test creds in certs/).
"""

from utils.certificates_v2 import CertificateGeneratorV2, sign_pdf

data = {
    "genebank": "Gotlandskanin",
    "genebank_number": "G1274",
    "genebank_aki": "2301",
    "name": "Bruno",
    "sex": "Hane",
    "birth_date": "2023-05-10",
    "color": "Grå",
    "eye_color": "Brun",
    "claw_color": "Ljus",
    "belly_color": "Vit",
    "hair_notes": "Normalt",
    "litter_size": "6",
    "litter_size6w": "5",
    "photos": "Ja",
    "notes": "Avelsdjur, mycket lugn och fin.",
    "color_note": "Jämn grå täckning, vit bläs.",
    "foot_ring": "",
    "color_code": "",
    "digital_certificate": "100001",
    "fullname": "Anna Exempel",
    "herd": "G1274",
    "issue_date": "2026-07-06",
    "public_url": "gotlandskaninen.se/stamboken/individ/G1274-2301",
    "replaces_date": "",
    "doc_hash_stub": "9F3A61C2",
    "F_genebank_number": "G1274",
    "F_genebank_aki": "2101",
    "F_name": "Pansen",
    "F_color": "Grå",
    "M_genebank_number": "G1274",
    "M_genebank_aki": "2102",
    "M_name": "Moringen",
    "M_color": "Vit",
    "FF_genebank_number": "G1274",
    "FF_genebank_aki": "1901",
    "FF_name": "Faransen",
    "FF_color": "Grå",
    "FM_genebank_number": "G1274",
    "FM_genebank_aki": "1902",
    "FM_name": "Farmansen",
    "FM_color": "Vit",
    "MF_genebank_number": "",
    "MF_genebank_aki": "",
    "MF_name": "",
    "MF_color": "",
    "MM_genebank_number": "",
    "MM_genebank_aki": "",
    "MM_name": "",
    "MM_color": "",
}

gen = CertificateGeneratorV2()
pdf = gen.generate_pedigree(data, qr_url="https://gotlandskaninen.se/stamboken/verifiera/100001")
signed = sign_pdf(
    pdf,
    reason="Signerat av Föreningen Gotlandskaninen för Gotlandskanin",
    contact_info="admin@gotlandskaninen.se",
)
path = "/tmp/cert_sample.pdf"
with open(path, "wb") as f:
    f.write(signed)
print(f"Sample: {len(signed)} bytes -> {path}")
