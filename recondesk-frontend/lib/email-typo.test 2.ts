import { suggestEmailCorrection, levenshteinDistance, COMMON_EMAIL_DOMAINS } from "./email-typo";

function assertEqual(actual: unknown, expected: unknown, desc: string) {
  if (actual !== expected) {
    throw new Error(`FAIL: ${desc} - Expected "${expected}", got "${actual}"`);
  }
  console.log(`PASS: ${desc}`);
}

// 1. Levenshtein distance checks
assertEqual(levenshteinDistance("gamil.com", "gmail.com"), 2, "Levenshtein gamil.com <-> gmail.com is 2");
assertEqual(levenshteinDistance("gmial.com", "gmail.com"), 2, "Levenshtein gmial.com <-> gmail.com is 2");
assertEqual(levenshteinDistance("outlok.com", "outlook.com"), 1, "Levenshtein outlok.com <-> outlook.com is 1");
assertEqual(levenshteinDistance("redifmail.com", "rediffmail.com"), 1, "Levenshtein redifmail.com <-> rediffmail.com is 1");
assertEqual(levenshteinDistance("gmail.com", "gmail.com"), 0, "Levenshtein exact match is 0");

// 2. suggestEmailCorrection checks
// User requirement: common misspellings like "gamil.com" -> suggest "gmail.com"
assertEqual(
  suggestEmailCorrection("kadamomkar9988@gamil.com"),
  "kadamomkar9988@gmail.com",
  "kadamomkar9988@gamil.com -> kadamomkar9988@gmail.com"
);
assertEqual(
  suggestEmailCorrection("user@gmial.com"),
  "user@gmail.com",
  "user@gmial.com -> user@gmail.com"
);
assertEqual(
  suggestEmailCorrection("user@gmaill.com"),
  "user@gmail.com",
  "user@gmaill.com -> user@gmail.com"
);
assertEqual(
  suggestEmailCorrection("user@yaho.com"),
  "user@yahoo.com",
  "user@yaho.com -> user@yahoo.com"
);
assertEqual(
  suggestEmailCorrection("user@outlok.com"),
  "user@outlook.com",
  "user@outlok.com -> user@outlook.com"
);
assertEqual(
  suggestEmailCorrection("user@hotmial.com"),
  "user@hotmail.com",
  "user@hotmial.com -> user@hotmail.com"
);
assertEqual(
  suggestEmailCorrection("user@icoud.com"),
  "user@icloud.com",
  "user@icoud.com -> user@icloud.com"
);
assertEqual(
  suggestEmailCorrection("user@redifmail.com"),
  "user@rediffmail.com",
  "user@redifmail.com -> user@rediffmail.com"
);

// 3. Exact matches should return null (no suggestion)
assertEqual(
  suggestEmailCorrection("kadamomkar9988@gmail.com"),
  null,
  "kadamomkar9988@gmail.com exact match returns null"
);
assertEqual(
  suggestEmailCorrection("user@rediffmail.com"),
  null,
  "user@rediffmail.com exact match returns null"
);

// 4. Custom/unusual CA firm domains should return null (distance > 2, not falsely corrected)
assertEqual(
  suggestEmailCorrection("ca@myfirmandco.in"),
  null,
  "ca@myfirmandco.in returns null"
);
assertEqual(
  suggestEmailCorrection("partner@kadamandassociates.com"),
  null,
  "partner@kadamandassociates.com returns null"
);

// 5. Invalid / edge inputs
assertEqual(suggestEmailCorrection(""), null, "empty string returns null");
assertEqual(suggestEmailCorrection("plainaddress"), null, "no @ returns null");
assertEqual(suggestEmailCorrection("@gmail.com"), null, "missing local part returns null");
assertEqual(suggestEmailCorrection("user@"), null, "missing domain returns null");

console.log("\nAll frontend email-typo tests passed successfully!");
