export interface IndianState {
  code: string;
  name: string;
}

export interface GstuqcCode {
  code: string;
  description: string;
}

export const INDIAN_STATES: IndianState[] = [
  { code: "01", name: "Jammu and Kashmir" },
  { code: "02", name: "Himachal Pradesh" },
  { code: "03", name: "Punjab" },
  { code: "04", name: "Chandigarh" },
  { code: "05", name: "Uttarakhand" },
  { code: "06", name: "Haryana" },
  { code: "07", name: "Delhi" },
  { code: "08", name: "Rajasthan" },
  { code: "09", name: "Uttar Pradesh" },
  { code: "10", name: "Bihar" },
  { code: "11", name: "Sikkim" },
  { code: "12", name: "Arunachal Pradesh" },
  { code: "13", name: "Nagaland" },
  { code: "14", name: "Manipur" },
  { code: "15", name: "Mizoram" },
  { code: "16", name: "Tripura" },
  { code: "17", name: "Meghalaya" },
  { code: "18", name: "Assam" },
  { code: "19", name: "West Bengal" },
  { code: "20", name: "Jharkhand" },
  { code: "21", name: "Odisha" },
  { code: "22", name: "Chhattisgarh" },
  { code: "23", name: "Madhya Pradesh" },
  { code: "24", name: "Gujarat" },
  { code: "26", name: "Dadra and Nagar Haveli and Daman and Diu" },
  { code: "27", name: "Maharashtra" },
  { code: "29", name: "Karnataka" },
  { code: "30", name: "Goa" },
  { code: "31", name: "Lakshadweep" },
  { code: "32", name: "Kerala" },
  { code: "33", name: "Tamil Nadu" },
  { code: "34", name: "Puducherry" },
  { code: "35", name: "Andaman and Nicobar Islands" },
  { code: "36", name: "Telangana" },
  { code: "37", name: "Andhra Pradesh" },
  { code: "38", name: "Ladakh" },
  { code: "97", name: "Other Territory" },
  { code: "99", name: "Other Territory / Overseas" },
];

export function getStateNameByCode(code?: string | null, fallback: string = ""): string {
  if (!code) return fallback;
  const cleanCode = code.trim().padStart(2, "0");
  const found = INDIAN_STATES.find((s) => s.code === cleanCode);
  if (found) return found.name;
  return fallback || `State (${cleanCode})`;
}

export const GST_UQC_CODES: GstuqcCode[] = [
  { code: "BAG", description: "BAGS" },
  { code: "BAL", description: "BALE" },
  { code: "BDL", description: "BUNDLES" },
  { code: "BKL", description: "BUCKLES" },
  { code: "BOU", description: "BILLION OF UNITS" },
  { code: "BOX", description: "BOX" },
  { code: "BTL", description: "BOTTLES" },
  { code: "BUN", description: "BUNCHES" },
  { code: "CAN", description: "CANS" },
  { code: "CBM", description: "CUBIC METERS" },
  { code: "CCM", description: "CUBIC CENTIMETERS" },
  { code: "CMS", description: "CENTIMETERS" },
  { code: "DOZ", description: "DOZENS" },
  { code: "DRS", description: "DRUMS" },
  { code: "GGR", description: "GREAT GROSS" },
  { code: "GMS", description: "GRAMMES" },
  { code: "GRS", description: "GROSS" },
  { code: "GYD", description: "GROSS YARDS" },
  { code: "HRS", description: "HOURS" },
  { code: "KGS", description: "KILOGRAMS" },
  { code: "KLR", description: "KILOLITRE" },
  { code: "KME", description: "KILOMETRE" },
  { code: "MLT", description: "MILLILITRE" },
  { code: "MTR", description: "METERS" },
  { code: "MTS", description: "METRIC TON" },
  { code: "NOS", description: "NUMBERS" },
  { code: "PAC", description: "PACKETS" },
  { code: "PCS", description: "PIECES" },
  { code: "PRS", description: "PAIRS" },
  { code: "QTL", description: "QUINTAL" },
  { code: "SET", description: "SETS" },
  { code: "SQF", description: "SQUARE FEET" },
  { code: "SQM", description: "SQUARE METERS" },
  { code: "SQY", description: "SQUARE YARDS" },
  { code: "TBS", description: "TABLETS" },
  { code: "THD", description: "THOUSANDS" },
  { code: "TON", description: "TONNES" },
  { code: "TUB", description: "TUBES" },
  { code: "UGS", description: "US GALLONS" },
  { code: "UNT", description: "UNITS" },
  { code: "YDS", description: "YARDS" },
  { code: "OTH", description: "OTHERS" },
];
