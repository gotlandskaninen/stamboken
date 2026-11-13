import { Box, Typography } from "@mui/material";
import { PageHeader } from "@/components/public/PageHeader";
import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = { title: "Integritetspolicy" };

const CONTACT = "dataskydd@gotlandskaninen.se";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Box component="section" sx={{ mt: 12, "&:first-of-type": { mt: 0 } }}>
      <Typography variant="h4" component="h2" sx={{ m: 0, mb: 3 }}>
        {title}
      </Typography>
      {children}
    </Box>
  );
}

const contactLink = <a href={`mailto:${CONTACT}`}>{CONTACT}</a>;

export default function IntegritetspolicyPage() {
  return (
    <>
      <PageHeader
        section="Integritetspolicy"
        title="Integritetspolicy"
        lede="Så behandlar Föreningen Gotlandskaninen dina personuppgifter: vilka uppgifter vi har, varför vi har dem, vilka som ser dem och vad du kan begära av oss."
      />
      <Box component="section" sx={{ p: { xs: "40px 24px", md: "80px 56px" } }}>
        <Box
          sx={{
            maxWidth: "42rem",
            fontSize: "17px",
            lineHeight: 1.65,
            color: "ink.2",
            "& p": { m: 0, mt: 4 },
            "& h2 + p": { mt: 0 },
            "& ul": { m: 0, mt: 3, pl: 6 },
            "& li": { mt: 1.5 },
            "& a": {
              color: "inherit",
              "@media (pointer: coarse)": {
                display: "inline-block",
                minHeight: 44,
                lineHeight: "44px",
              },
            },
          }}
        >
          <Section title="Vem ansvarar för uppgifterna">
            <p>
              Föreningen Gotlandskaninen, organisationsnummer 834001-9549, är
              personuppgiftsansvarig för uppgifterna i medlemsregistret, i
              Stamboken Online och på den här webbplatsen. Har du frågor om hur
              vi behandlar dina uppgifter, eller vill du använda någon av dina
              rättigheter, mejla {contactLink}.
            </p>
          </Section>

          <Section title="När du besöker webbplatsen">
            <p>
              Webbplatsen mäter inte besök och har inga kakor för statistik
              eller reklam. Sidorna sätter inga kakor förrän du öppnar
              inloggningssidan.
            </p>
            <ul>
              <li>
                Servern loggar varje besök: din IP-adress, tidpunkten, adressen
                du hämtade och vilken webbläsare du använder. Loggarna behövs
                för felsökning och säkerhet (berättigat intresse) och sparas i
                ungefär tre månader.
              </li>
              <li>
                På inloggningssidan laddas Googles inloggningstjänst. Den sätter
                en kaka (g_state) i din webbläsare, och Google får din IP-adress
                och uppgifter om din webbläsare, även om du inte loggar in.
              </li>
              <li>
                När du loggar in sätts två kakor som tjänsten behöver: en som
                håller dig inloggad i upp till 31 dagar och en som minns om du
                arbetar i riktiga stamboken eller i testmiljön. Formulär du har
                påbörjat sparas i din egen webbläsare tills du skickar dem.
              </li>
            </ul>
          </Section>

          <Section title="När du ansöker om medlemskap">
            <p>
              I ansökan lämnar du namn och e-postadress. Telefon, postadress,
              fakturaadress och det du berättar om dig själv är frivilligt, men
              utan postadress kan vi inte skicka medlemstidningen Koharen.
            </p>
            <p>
              Vi använder uppgifterna för att behandla ansökan och för att lägga
              in dig i medlemsregistret när du blir medlem. Det behövs för att
              du ska kunna bli medlem (avtal). Ansökan läses av dem som sköter
              medlemsregistret, av genbanksansvariga och av föreningens
              systemansvarig.
            </p>
            <p>Blir du inte medlem tar vi bort ansökan inom 12 månader.</p>
          </Section>

          <Section title="När du är medlem">
            <p>
              I medlemsregistret finns ditt medlemsnummer, namn, adress, telefon
              och e-postadress, när du gick med, om avgiften är betald och en
              eventuell fakturaadress. Ingår fler personer i medlemskapet, till
              exempel familjemedlemmar eller någon som sköter kaninerna åt dig,
              finns deras namn och kontaktuppgifter också. Lägger du själv in en
              annan person ska du berätta det för den personen och visa den här
              sidan.
            </p>
            <p>
              Vi använder uppgifterna för att ta emot medlemsavgiften, skicka
              Koharen, kalla till årsmöte och kunna nå dig i föreningens arbete.
              Det behövs för medlemskapet (avtal). Uppgifter om betalningar som
              ingår i bokföringen sparar vi i sju år, eftersom bokföringslagen
              kräver det (rättslig förpliktelse).
            </p>
            <ul>
              <li>
                Hela medlemsregistret kan läsas av dem som sköter det, av
                genbanksansvariga och av föreningens systemansvarig. Du ser
                själv uppgifterna om ditt eget medlemskap.
              </li>
              <li>
                Tryckeriet får namn, adress och medlemsnummer för att kunna
                skicka Koharen.{" "}
                <mark>
                  [BESLUT: stämmer det fortfarande, och raderar tryckeriet filen
                  efter utskicket?]
                </mark>
              </li>
              <li>
                I Koharen publicerar vi bara de kontaktuppgifter du själv har
                sagt ja till (samtycke). Du kan ändra dig när du vill.
              </li>
            </ul>
            <p>
              Vi sparar uppgifterna så länge du är medlem. När medlemskapet
              upphör tar vi bort eller anonymiserar uppgifterna inom 12 månader.
            </p>
          </Section>

          <Section title="När du har en genbanksbesättning">
            <p>
              I Stamboken Online finns besättningens nummer och namn,
              kontaktperson, adress, telefon, e-postadress, eventuell webbplats
              och koordinater, samt bankkonto för utbetalning av stöd. Där finns
              också dina kaniner, parningar, kullar och årsrapporter.
            </p>
            <p>
              Uppgifterna behövs för genbanksavtalet mellan dig och föreningen
              (avtal) och för att raserna ska kunna bevaras, vilket kräver att
              varje kanins härstamning går att följa (berättigat intresse).
            </p>
            <ul>
              <li>
                Du själv, genbanksansvarig för rasen och föreningens
                systemansvarig ser alla uppgifter om besättningen.
              </li>
              <li>
                Andra inloggade medlemmar ser besättningens nummer och namn och
                dina kaniner. Kontaktuppgifterna ser de bara om du själv har
                valt att visa dem.
              </li>
              <li>
                Bankkontot används för att betala ut stöd.{" "}
                <mark>
                  [BESLUT: får Jordbruksverket fortfarande ta del av
                  utbetalningsunderlaget med namn och bankkonto?]
                </mark>
              </li>
              <li>
                Varje ändring i stamboken loggas med användare, tidpunkt och
                IP-adress, så att fel kan spåras och rättas. Loggen sparas tills
                vidare.
              </li>
            </ul>
            <p>
              Uppgifterna om kaninerna och deras härstamning sparas tills
              vidare, tillsammans med besättningens nummer. Kontaktuppgifterna{" "}
              <mark>
                [BESLUT: hur länge sparas kontaktuppgifter för en avslutad
                genbanksbesättning? Förslag: 12 månader, bankkontot tas bort
                efter sista utbetalningen.]
              </mark>
            </p>
          </Section>

          <Section title="Ditt konto i Stamboken Online">
            <p>
              Kontot innehåller användarnamn, namn, e-postadress, din roll och
              när du senast var inloggad. Loggar du in med Google sparas också
              namnet och profilbilden från ditt föreningskonto. Lösenord sparas
              aldrig i klartext. Kontot behövs för att bara rätt person ska
              kunna se och ändra uppgifter (avtal och berättigat intresse).
            </p>
          </Section>

          <Section title="Digitala genbanksintyg">
            <p>
              Den som utfärdar ett digitalt genbanksintyg står med sitt namn på
              intyget. Alla som har intygets QR-kod eller länk kan öppna en sida
              som visar kaninens namn och nummer, ras, intygsnummer, datum och
              namnet på den som utfärdade intyget. Det gör vi för att en köpare
              ska kunna kontrollera att intyget är äkta (berättigat intresse).
            </p>
          </Section>

          <Section title="Föreningskonto, e-post och forum">
            <p>
              Som medlem kan du få ett föreningskonto: en e-postadress på
              gotlandskaninen.se hos Google Workspace. Med det loggar du in i
              Stamboken Online och i medlemsforumet. När du mejlar föreningen
              lagras mejlet hos Google och läses av den funktionär som har
              adressen. I forumet sparas ditt användarnamn, din e-postadress och
              det du skriver.{" "}
              <mark>
                [BESLUT: forumet ska läggas ner. Förslag: konton och inlägg tas
                bort när det stängs.]
              </mark>
            </p>
          </Section>

          <Section title="Vilka som får dina uppgifter">
            <p>
              Vi säljer aldrig personuppgifter och lämnar inte ut dem för
              reklam. De här får uppgifter för att föreningen ska kunna sköta
              sitt arbete:
            </p>
            <ul>
              <li>
                Google, som levererar föreningens e-post, föreningskonton,
                inloggning och delade dokument. Google kan behandla uppgifter
                utanför EU och EES. Överföringen stöds av EU-kommissionens
                beslut om adekvat skyddsnivå för USA och av
                standardavtalsklausuler.
              </li>
              <li>
                Safespring, som tillhandahåller servrar och lagring för
                Stamboken Online i datacenter i Stockholm.
              </li>
              <li>Tryckeriet som skickar ut Koharen.</li>
              <li>Jordbruksverket, när stödet till genbankerna redovisas.</li>
            </ul>
            <p>
              Säkerhetskopiorna är krypterade och lagras hos Safespring i
              Stockholm och i föreningens Google Drive. De sparas i upp till 12
              månader. En uppgift som vi har tagit bort kan därför finnas kvar i
              en säkerhetskopia under den tiden.
            </p>
          </Section>

          <Section title="Dina rättigheter">
            <p>Du har rätt att:</p>
            <ul>
              <li>få veta vilka uppgifter vi har om dig och få en kopia</li>
              <li>få felaktiga uppgifter rättade</li>
              <li>
                få uppgifter raderade när vi inte längre behöver dem eller måste
                spara dem enligt lag
              </li>
              <li>begära att vi begränsar behandlingen</li>
              <li>
                få ut de uppgifter du själv har lämnat i ett format som går att
                flytta
              </li>
              <li>ta tillbaka ett samtycke när du vill.</li>
            </ul>
            <p>
              Du har också rätt att invända mot behandling som vi stöder på
              berättigat intresse. Då prövar vi om våra skäl väger tyngre än
              dina.
            </p>
            <p>
              Mejla {contactLink}. Vi svarar inom en månad. Är du inte nöjd kan
              du klaga hos{" "}
              <a href="https://www.imy.se">Integritetsskyddsmyndigheten</a>.
            </p>
          </Section>

          <p>
            <mark>[BESLUT: datum då styrelsen antog texten.]</mark>
          </p>
        </Box>
      </Box>
    </>
  );
}
