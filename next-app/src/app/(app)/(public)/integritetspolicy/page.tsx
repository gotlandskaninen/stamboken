import { Box, Typography } from "@mui/material";
import { PageHeader } from "@/components/public/PageHeader";
import { TEXT_MAX_WIDTH, TEXT_ROW } from "@/components/blocks/textColumn";
import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = { title: "Integritetspolicy" };

const CONTACT = "dataskydd@gotlandskaninen.se";

// Same grid as the CMS text pages: the heading in the margin column.
function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Box
      component="section"
      sx={{
        ...TEXT_ROW,
        rowGap: 3,
        py: { xs: 7, md: 9 },
        borderTop: "1px solid var(--sb-line)",
        "&:first-of-type": { pt: 0, borderTop: 0 },
      }}
    >
      <Typography
        variant="h4"
        component="h2"
        sx={{ m: 0, fontWeight: 400, fontSize: { xs: "24px", md: "26px" } }}
      >
        {title}
      </Typography>
      <Box sx={{ minWidth: 0, "& > :first-child": { mt: 0 } }}>{children}</Box>
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
            maxWidth: TEXT_MAX_WIDTH,
            fontSize: "17px",
            lineHeight: 1.65,
            color: "ink.2",
            "& p": { m: 0, mt: 4 },
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
              rättigheter, mejla {contactLink}. Vill du ha den här texten på
              papper kan du be genbanksansvarig eller mejla samma adress.
            </p>
          </Section>

          <Section title="När du besöker webbplatsen">
            <p>
              Webbplatsen mäter inte besök och har inga kakor för statistik
              eller reklam. Våra egna sidor sätter inga kakor förrän du öppnar
              inloggningssidan.
            </p>
            <ul>
              <li>
                Servern loggar varje besök: din IP-adress, tidpunkten, adressen
                du hämtade och vilken webbläsare du använder. Loggarna behövs
                för felsökning och säkerhet (berättigat intresse) och sparas i
                högst 90 dagar på servern. Säkerhetsloggar, till exempel besök,
                inloggningar och nekad åtkomst, sparas dessutom i upp till 12
                månader i ett skyddat arkiv hos Safespring i Stockholm, så att
                vi kan utreda ett intrång som upptäcks sent. Under de första 90
                dagarna går de inte att radera.
              </li>
              <li>
                På inloggningssidan laddas Googles inloggningstjänst. Google får
                då din IP-adress och uppgifter om din webbläsare, och tjänsten
                kan sätta en kaka (g_state), även om du inte loggar in.
              </li>
              <li>
                När du loggar in sätts två kakor som tjänsten behöver: en som
                håller dig inloggad tills du loggar ut, stänger webbläsaren
                eller har varit inaktiv i 31 dagar, och en som minns om du
                arbetar i riktiga stamboken eller i testmiljön.
              </li>
              <li>
                Vissa val och utkast sparas i din egen webbläsare, till exempel
                att du har stängt en informationsruta eller påbörjat en
                registrering av en parning eller kull. De skickas inte till oss
                förrän du sparar.
              </li>
              <li>
                Bäddar vi in en film från YouTube eller Vimeo på en sida laddas
                den därifrån, och de tjänsterna kan då sätta egna kakor.
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
              systemansvarig. De antecknar beslutet och, vid avslag, skälet.
            </p>
            <p>Blir du inte medlem tar vi bort ansökan inom 12 månader.</p>
          </Section>

          <Section title="När du är medlem">
            <p>
              I medlemsregistret finns ditt medlemsnummer, namn, adress, telefon
              och e-postadress, när du gick med, om avgiften är betald och en
              eventuell fakturaadress. Den som sköter registret kan också skriva
              en anteckning om medlemskapet, till exempel om en betalning.
            </p>
            <p>
              Vi använder uppgifterna för att ta emot medlemsavgiften, skicka
              Koharen, kalla till årsmöte och kunna nå dig i föreningens arbete.
              Det behövs för medlemskapet (avtal). Uppgifter om betalningar som
              ingår i bokföringen sparar vi i sju år efter det år de gäller,
              eftersom bokföringslagen kräver det (rättslig förpliktelse).
            </p>
            <ul>
              <li>
                Hela medlemsregistret kan läsas av dem som sköter det, av
                genbanksansvariga och av föreningens systemansvarig. Du ser
                själv uppgifterna om ditt eget medlemskap. Ändringar i registret
                loggas med vem som gjorde dem och när.
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
                I Koharen publicerar vi bara de kontaktuppgifter som
                huvudmedlemmen har sagt ja till (samtycke). Valet gäller alla
                personer i medlemskapet och kan ändras när som helst. Det som
                redan är tryckt går inte att ta tillbaka.
              </li>
            </ul>
            <p>
              Vi sparar uppgifterna så länge du är medlem. När medlemskapet
              upphör tar vi bort eller anonymiserar uppgifterna inom 12 månader.
            </p>
          </Section>

          <Section title="När någon annan har lämnat dina uppgifter">
            <p>
              En huvudmedlem kan lägga in familjemedlemmar och personer som
              sköter kaninerna i sitt medlemskap, och kan ange en annan
              mottagare för fakturan. Då har vi fått ditt namn och dina
              kontaktuppgifter från huvudmedlemmen och inte från dig. Vi
              använder dem på samma sätt och lika länge som medlemmens egna
              uppgifter, och du har samma rättigheter.{" "}
              <mark>
                [BESLUT: hur får den som lagts in av någon annan veta det?
                Förslag: föreningen mejlar personen inom en månad.]
              </mark>
            </p>
          </Section>

          <Section title="När du har en genbanksbesättning">
            <p>
              I Stamboken Online finns besättningens nummer och namn,
              kontaktperson, adress, telefon, e-postadress, eventuell webbplats
              och koordinater, samt bankkonto för utbetalning av stöd. Där finns
              också dina kaniner, parningar och kullar, foton du laddar upp, och
              dina årsrapporter med dina val om vad som får publiceras. Vid
              varje rapporterad händelse står vem som rapporterade den.
            </p>
            <p>
              Uppgifterna behövs för genbanksavtalet mellan dig och föreningen
              (avtal) och för att raserna ska kunna bevaras, vilket kräver att
              varje kanins härstamning går att följa (berättigat intresse).
            </p>
            <ul>
              <li>
                Du själv, de som har fått åtkomst till besättningen (till
                exempel en skötare), genbanksansvarig för rasen och föreningens
                systemansvarig ser alla uppgifter om besättningen.
              </li>
              <li>
                Andra inloggade medlemmar ser besättningens nummer och namn och
                dina kaniner. Kontaktuppgifter och bankkonto är dolda för dem
                från början. De visas bara om fältet har ställts in som synligt,
                av dig eller av genbanksansvarig.
              </li>
              <li>
                Bankkontot används för att betala ut stöd.{" "}
                <mark>
                  [BESLUT: får Jordbruksverket fortfarande ta del av
                  utbetalningsunderlaget med namn och bankkonto?]
                </mark>
              </li>
              <li>
                Ändringar av kaniner, parningar, kullar, besättningar och konton
                loggas med användare, tidpunkt, IP-adress och det gamla och det
                nya värdet, så att fel kan spåras och rättas (berättigat
                intresse).{" "}
                <mark>
                  [BESLUT: hur länge sparas IP-adressen i ändringsloggen?
                  Förslag: 12 månader; resten av loggen så länge uppgiften den
                  gäller finns kvar.]
                </mark>
              </li>
              <li>
                Testmiljön är en kopia av den riktiga stamboken, så att du kan
                öva utan att ändra något på riktigt. Kopian innehåller samma
                uppgifter. Alla som har ett föreningskonto kan logga in i
                testmiljön, också den vars konto ännu inte är godkänt för den
                riktiga stamboken, och ser där det som andra inloggade medlemmar
                ser.
              </li>
            </ul>
            <p>
              Uppgifterna om kaninerna och deras härstamning sparas så länge
              stamboken finns, tillsammans med besättningens nummer.
              Kontaktuppgifterna tar vi bort inom 12 månader efter att
              genbanksbesättningen har avslutats, och bankkontot när det sista
              stödet är utbetalt.
            </p>
          </Section>

          <Section title="Ditt konto i Stamboken Online">
            <p>
              Kontot innehåller användarnamn, namn, e-postadress, vad du får
              läsa och ändra, och när du senast använde tjänsten. Loggar du in
              med Google sparas också namnet, e-postadressen och länken till
              profilbilden från ditt föreningskonto. Du kan ladda upp en egen
              profilbild. Lösenord sparas aldrig i klartext.
            </p>
            <p>
              Kontot behövs för att du ska kunna använda Stamboken Online och
              för att bara rätt person ska se och ändra uppgifter (avtal). Det
              finns kvar så länge du är medlem eller har en genbanksbesättning.
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
              Stamboken Online och i medlemsforumet. Kontot ingår i medlemskapet
              (avtal). När du mejlar föreningen lagras mejlet hos Google och
              läses av den funktionär som har adressen, för att vi ska kunna
              svara dig (berättigat intresse). I forumet sparas ditt
              användarnamn, din e-postadress och det du skriver. Forumet ska
              läggas ner, och då tas konton och inlägg bort.
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
                utanför EU och EES. Överföringen till USA stöds av
                EU-kommissionens beslut om att skyddet där är tillräckligt
                (EU–US Data Privacy Framework) och av EU:s standardavtal för
                överföring av personuppgifter, som ingår i vårt avtal med
                Google.
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
                begära att få uppgifter raderade; i vissa fall behöver vi
                behålla dem, till exempel när en lag kräver det
              </li>
              <li>begära att vi begränsar behandlingen</li>
              <li>
                få ut de uppgifter du själv har lämnat, när vi behandlar dem med
                stöd av avtal eller samtycke, i ett format som går att flytta
              </li>
              <li>
                ta tillbaka ett samtycke när du vill; det påverkar inte det vi
                redan har gjort med stöd av samtycket.
              </li>
            </ul>
            <p>
              Du har också rätt att invända mot behandling som vi stöder på
              berättigat intresse. Då prövar vi om våra skäl väger tyngre än
              dina.
            </p>
            <p>
              Vi fattar inga beslut om dig med enbart automatik. Mejla{" "}
              {contactLink} om du vill använda en rättighet. Vi svarar inom en
              månad. Du kan också när som helst klaga direkt hos{" "}
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
