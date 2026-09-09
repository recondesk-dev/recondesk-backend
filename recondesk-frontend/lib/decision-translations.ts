/**
 * Localization helper for Decision Layer strings (What, Why, Next, Discrepancies).
 * Translates backend generated decision templates to Hindi while preserving GST terms.
 */

const EXACT_TRANSLATIONS: Record<string, string> = {
  // L1 Exact
  "Exact match found": "सटीक मिलान मिला (Exact match)",
  "Invoice number, amount, and date all match within rounding tolerance":
    "इनवॉइस नंबर, राशि और तारीख सभी राउंडिंग टॉलरेंस के भीतर मेल खाते हैं",
  "No action required. ITC can be claimed as filed.":
    "किसी कार्रवाई की आवश्यकता नहीं है। दाखिल किए अनुसार ITC का दावा किया जा सकता है।",

  // L2 Normalized
  "No action required — formatting differs, amounts align":
    "कार्रवाई की आवश्यकता नहीं — फॉर्मेटिंग भिन्न है, राशियां समान हैं",

  // GSTIN mismatch
  "GSTIN mismatch — verify supplier identity":
    "GSTIN मिसमैच — सप्लायर पहचान सत्यापित करें",
  "Supplier GSTIN mismatch (possible typo)":
    "सप्लायर GSTIN मिसमैच (संभावित टाइपो)",
  "Invoice number and amount match a purchase register entry but the supplier GSTIN differs":
    "इनवॉइस नंबर और राशि परचेज रजिस्टर प्रविष्टि से मेल खाती है लेकिन सप्लायर GSTIN भिन्न है",

  // Amount mismatch
  "Invoice matched on identity fields but the taxable amount differs beyond auto-accept threshold":
    "इनवॉइस पहचान फ़ील्ड पर मेल खाता है लेकिन कर योग्य राशि ऑटो-स्वीकृति सीमा से अधिक भिन्न है",
  "Verify taxable value with supplier invoice copy. If confirmed, update purchase register.":
    "सप्लायर इनवॉइस कॉपी से कर योग्य मूल्य सत्यापित करें। पुष्टि होने पर परचेज रजिस्टर अपडेट करें।",

  // Duplicates & Candidates
  "Duplicate invoice — multiple entries found":
    "डुप्लिकेट इनवॉइस — एकाधिक प्रविष्टियां मिलीं",
  "The same invoice appears more than once; the system cannot determine which is the original":
    "एक ही इनवॉइस एक से अधिक बार दिखाई देता है; सिस्टम यह निर्धारित नहीं कर सकता कि मूल कौन सा है",
  "Identify the correct entry and remove or mark the duplicate(s). Do not claim ITC on duplicate bookings.":
    "सही प्रविष्टि की पहचान करें और डुप्लिकेट को हटाएं या चिह्नित करें। डुप्लिकेट बुकिंग पर ITC का दावा न करें।",
  "Duplicate Entry — same invoice booked twice in books":
    "डुप्लिकेट प्रविष्टि — बहीखाते में एक ही इनवॉइस दो बार दर्ज",
  "Identical GSTIN + invoice appears more than once in the purchase register":
    "परचेज रजिस्टर में समान GSTIN + इनवॉइस एक से अधिक बार दिखाई देता है",
  "Remove or mark the extra purchase-register row. Do not treat this as missing from GSTR-2B.":
    "अतिरिक्त परचेज-रजिस्टर पंक्ति को हटाएं या चिह्नित करें। इसे GSTR-2B से गायब न मानें।",
  "Multiple matching candidates — manual selection required":
    "एकाधिक मिलान उम्मीदवार — मैन्युअल चयन आवश्यक",
  "More than one purchase register entry could match this GSTR-2B invoice":
    "एक से अधिक परचेज रजिस्टर प्रविष्टियां इस GSTR-2B इनवॉइस से मेल खा सकती हैं",
  "Review all candidates and confirm the correct match. Mark the others as duplicates or separate transactions.":
    "सभी उम्मीदवारों की समीक्षा करें और सही मिलान की पुष्टि करें। अन्य को डुप्लिकेट के रूप में चिह्नित करें।",
  "PR_CLAIMED_BY_BETTER_MATCH": "Claimed by better-matched purchase register entry",
  "Claimed by better-matched purchase register entry": "Claimed by better-matched purchase register entry",

  // Possible match
  "Partial field overlap detected but confidence is below the auto-match threshold":
    "आंशिक फ़ील्ड ओवरलैप पाया गया लेकिन कॉन्फिडेंस ऑटो-मैच सीमा से कम है",
  "Verify with physical invoice. If the same transaction, correct the mismatched fields in the purchase register.":
    "भौतिक इनवॉइस से सत्यापित करें। यदि वही लेनदेन है, तो परचेज रजिस्टर में फ़ील्ड सही करें।",
  "Examine GSTR-2B and purchase register entries side by side. Resolve discrepancies before filing GSTR-3B.":
    "GSTR-2B और परचेज रजिस्टर प्रविष्टियों की साथ-साथ जांच करें। GSTR-3B दाखिल करने से पहले विसंगतियों का समाधान करें।",

  // Period boundary
  "Invoice date crosses GST return period boundary":
    "इनवॉइस की तारीख GST रिटर्न अवधि सीमा को पार करती है",
  "Confirm which return period this supply belongs to. Align the purchase register date with the correct period before claiming ITC in GSTR-3B.":
    "पुष्टि करें कि यह आपूर्ति किस रिटर्न अवधि की है। GSTR-3B में ITC दावा करने से पहले परचेज रजिस्टर तारीख संरेखित करें।",

  // Missed ITC & Wrongful ITC
  "Available in 2B but Missing in Books":
    "2B में उपलब्ध लेकिन बुक्स में गायब",
  "Invoice not reflected in GSTR-2B":
    "इनवॉइस GSTR-2B में परिलक्षित नहीं है",
  "Composition Scheme — Ineligible for ITC":
    "Composition Scheme — ITC के लिए अपात्र",
  "No ITC can be claimed. Treat total invoice value as purchase expense/cost.":
    "कोई ITC दावा नहीं किया जा सकता। कुल इनवॉइस मूल्य को खरीद व्यय/लागत मानें।",

  // Rule 37 & 37A
  "Invoice unpaid beyond 180 days -- ITC reversal is now mandatory":
    "180 दिनों से अधिक समय से इनवॉइस अवैतनिक -- ITC रिवर्सल अनिवार्य है",
  "Section 16(2) with Rule 37 requires ITC reversal if supplier unpaid after 180 days":
    "Section 16(2) और Rule 37 के तहत 180 दिनों के बाद सप्लायर अवैतनिक होने पर ITC रिवर्सल आवश्यक है",
  "Section 16(2) limits ITC if consideration not paid within 180 days":
    "180 दिनों के भीतर भुगतान न होने पर Section 16(2) ITC को सीमित करता है",
  "GSTR-1 filed after the statutory due date (11th of following month)":
    "वैधानिक नियत तारीख (अगले महीने की 11 तारीख) के बाद GSTR-1 दाखिल किया गया",
  "ITC unavailable in GSTR-2B (Supplier GSTR-3B Non-Filer / Rule 37A)":
    "GSTR-2B में ITC अनुपलब्ध (सप्लायर GSTR-3B नॉन-फाइलर / Rule 37A)",

  // General fallbacks
  "Mismatch detected": "विसंगति का पता चला",
  "Unable to determine specific reason": "विशिष्ट कारण निर्धारित करने में असमर्थ",
  "Review manually with CA before claiming ITC.": "ITC का दावा करने से पहले CA के साथ मैन्युअल समीक्षा करें।",
};

const PATTERN_REPLACEMENTS: Array<[RegExp, (match: RegExpMatchArray) => string]> = [
  // Confirm correct GSTIN with supplier ...
  [
    /^Confirm correct GSTIN with supplier\s*(.*?)\.?\s*Update purchase register if supplier migrated or amended their GSTIN\.?$/i,
    (m) => {
      const gstin = m[1]?.trim() && m[1].trim() !== "?" ? ` (${m[1].trim()})` : "";
      return `सप्लायर${gstin} से सही GSTIN की पुष्टि करें। यदि सप्लायर ने अपना GSTIN बदला है तो परचेज रजिस्टर अपडेट करें।`;
    },
  ],
  // Verify manually — X% confidence, discrepancy of Y
  [
    /^Verify manually\s*—\s*(\d+)%\s*confidence,\s*discrepancy of\s*(.*)$/i,
    (m) => `मैन्युअल रूप से सत्यापित करें — ${m[1]}% कॉन्फिडेंस, ${m[2]} का अंतर`,
  ],
  // Possible match — X% confidence
  [
    /^Possible match\s*—\s*(\d+)%\s*confidence$/i,
    (m) => `संभावित मिलान — ${m[1]}% कॉन्फिडेंस`,
  ],
  // Review required — X% confidence
  [
    /^Review required\s*—\s*(\d+)%\s*confidence$/i,
    (m) => `समीक्षा आवश्यक — ${m[1]}% कॉन्फिडेंस`,
  ],
  // Invoice matched but amount differs by X
  [
    /^Invoice matched but amount differs by\s*(.*)$/i,
    (m) => `इनवॉइस मैच हुआ लेकिन राशि में ${m[1]} का अंतर है`,
  ],
  // Request revised invoice or debit/credit note from ...
  [
    /^Request revised invoice or debit\/credit note from\s*(.*?)\.\s*Do not claim full ITC until resolved\.?$/i,
    (m) => `सप्लायर ${m[1] || ""} से संशोधित इनवॉइस या डेबिट/क्रेडिट नोट का अनुरोध करें। समाधान होने तक पूर्ण ITC का दावा न करें।`,
  ],
  // Compare physical invoice with GSTR-2B entry. Reconcile the X difference...
  [
    /^Compare physical invoice with GSTR-2B entry\.\s*Reconcile the\s*(.*?)\s*difference with supplier before claiming ITC\.?$/i,
    (m) => `भौतिक इनवॉइस की GSTR-2B प्रविष्टि से तुलना करें। ITC का दावा करने से पहले ${m[1]} अंतर का समाधान करें।`,
  ],
  // Reverse ITC of X in next GSTR-3B...
  [
    /^Reverse ITC of\s*(.*?)\s*in next GSTR-3B\.\s*Pay supplier immediately or face 24% interest\.?$/i,
    (m) => `अगले GSTR-3B में ${m[1]} ITC रिवर्स करें। सप्लायर को तुरंत भुगतान करें अन्यथा 24% ब्याज लगेगा।`,
  ],
  // Pay supplier by X or face Y ITC reversal
  [
    /^Pay supplier by\s*(.*?)\s*or face\s*(.*?)\s*ITC reversal$/i,
    (m) => `${m[1]} तक सप्लायर को भुगतान करें अन्यथा ${m[2]} ITC रिवर्सल का सामना करना पड़ेगा`,
  ],
  // Supplier payment due in X days (Y)
  [
    /^Supplier payment due in\s*(\d+)\s*days\s*\((.*?)\)$/i,
    (m) => `सप्लायर भुगतान ${m[1]} दिनों में देय (${m[2]})`,
  ],
  // Contact X to confirm filing status...
  [
    /^Contact\s*(.*?)\s*to confirm filing status\.\s*Do not claim this ITC in GSTR-3B until it appears in GSTR-2B\.?$/i,
    (m) => `फाइलिंग स्थिति की पुष्टि के लिए सप्लायर ${m[1]} से संपर्क करें। GSTR-2B में आने तक GSTR-3B में इस ITC का दावा न करें।`,
  ],
  // Hold on IMS and do not claim in GSTR-3B. Follow up with X...
  [
    /^Hold on IMS and do not claim in GSTR-3B\.\s*Follow up with\s*(.*?)\s*to file GSTR-3B\..*$/i,
    (m) => `IMS पर होल्ड करें और GSTR-3B में दावा न करें। GSTR-3B फाइल करने के लिए सप्लायर ${m[1]} से संपर्क करें।`,
  ],
  // Normalized invoice match: X <-> Y
  [
    /^Normalized invoice match:\s*(.*?)\s*↔\s*(.*)$/i,
    (m) => `सामान्यीकृत इनवॉइस मिलान: ${m[1]} ↔ ${m[2]}`,
  ],
  // Invoice may be under Section 17(5) blocked credit: X
  [
    /^Invoice may be under Section 17\(5\) blocked credit:\s*(.*)$/i,
    (m) => `इनवॉइस Section 17(5) ब्लॉक्ड क्रेडिट के अंतर्गत हो सकता है: ${m[1]}`,
  ],
  // Locate physical invoice. If genuine, add to purchase register and claim ITC of X.
  [
    /^Locate physical invoice\.\s*If genuine, add to purchase register and claim ITC of\s*(.*?)\.?$/i,
    (m) => `भौतिक इनवॉइस खोजें। यदि सही है, तो परचेज रजिस्टर में जोड़ें और ${m[1]} ITC का दावा करें।`,
  ],
  // Evaluate supplier compliance. X ITC at risk due to late filing.
  [
    /^Evaluate supplier compliance\.\s*(.*?)\s*ITC at risk due to late filing\.?$/i,
    (m) => `सप्लायर अनुपालन का मूल्यांकन करें। देर से फाइलिंग के कारण ${m[1]} ITC जोखिम में है।`,
  ],
];

export function localizeDecisionText(
  text: string | null | undefined,
  locale: string
): string {
  if (!text) return "";
  const trimmed = text.trim();
  if (locale !== "hi") return trimmed;

  // 1. Direct dictionary match
  if (EXACT_TRANSLATIONS[trimmed]) {
    return EXACT_TRANSLATIONS[trimmed];
  }

  // 2. Pattern matching
  for (const [pattern, replacer] of PATTERN_REPLACEMENTS) {
    const match = trimmed.match(pattern);
    if (match) {
      return replacer(match);
    }
  }

  return trimmed;
}

export function localizeDiscrepancyReason(
  reason: string | null | undefined,
  locale: string
): string {
  if (!reason) return "";
  if (locale !== "hi") return reason;

  const normalized = reason.toUpperCase().replace(/\s+/g, "_");
  switch (normalized) {
    case "GSTIN_MISMATCH":
      return "GSTIN मिसमैच";
    case "AMOUNT_MISMATCH":
    case "AMOUNT_DIFF":
      return "राशि मिसमैच";
    case "INVOICE_NUM_MISMATCH":
    case "INVOICE_MISMATCH":
      return "इनवॉइस # मिसमैच";
    case "DATE_MISMATCH":
      return "तारीख मिसमैच";
    case "ROUNDING_DIFF":
      return "राउंडिंग अंतर";
    case "DUPLICATE_ENTRY":
    case "DUPLICATE":
      return "डुप्लिकेट प्रविष्टि";
    case "PR_CLAIMED_BY_BETTER_MATCH":
      return "Claimed by better-matched purchase register entry";
    case "SECTION_17_5":
    case "SECTION17":
      return "Section 17(5)";
    case "RULE_37":
    case "RULE37":
      return "Rule 37";
    case "RULE_37A":
    case "RULE37A":
      return "Rule 37A";
    default:
      return reason;
  }
}
