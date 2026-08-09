/** Empty GSTR-3B Save body shape (CA enters/confirms every figure). */

export type Gstr3bTaxHeadFields = {
  txval: number | "";
  iamt: number | "";
  camt: number | "";
  samt: number | "";
  csamt: number | "";
};

export type ItcRowProps = {
  ty: string;
  iamt: number | "";
  camt: number | "";
  samt: number | "";
  csamt: number | "";
};

export type Gstr3bFiguresState = {
  gstin: string;
  ret_period: string;
  sup_details: {
    osup_det: Gstr3bTaxHeadFields;
    osup_zero: Gstr3bTaxHeadFields;
    osup_nil_exmp: Gstr3bTaxHeadFields;
    osup_nongst: Gstr3bTaxHeadFields;
    isup_rev: Gstr3bTaxHeadFields;
  };
  itc_elg: {
    itc_avl: ItcRowProps[];
    itc_rev: ItcRowProps[];
    itc_net: ItcRowProps[];
    itc_inelg: ItcRowProps[];
  };
  inward_sup: {
    isup_details: Array<{
      ty: string;
      inter: number | "";
      intra: number | "";
    }>;
  };
  intr_ltfee: {
    intr_details: {
      iamt: number | "";
      camt: number | "";
      samt: number | "";
      csamt: number | "";
    };
    ltfee_details: {
      camt: number | "";
      samt: number | "";
    };
  };
};

const EMPTY_TAX: Gstr3bTaxHeadFields = {
  txval: "",
  iamt: "",
  camt: "",
  samt: "",
  csamt: "",
};

const ITC_AVL_TYPES = ["IMPG", "IMPS", "ISRC", "ISD", "OTH"] as const;

function emptyItc(ty: string): ItcRowProps {
  return { ty, iamt: "", camt: "", samt: "", csamt: "" };
}

export function emptyGstr3bFigures(
  gstin = "",
  retPeriod = ""
): Gstr3bFiguresState {
  return {
    gstin,
    ret_period: retPeriod,
    sup_details: {
      osup_det: { ...EMPTY_TAX },
      osup_zero: { ...EMPTY_TAX },
      osup_nil_exmp: { ...EMPTY_TAX },
      osup_nongst: { ...EMPTY_TAX },
      isup_rev: { ...EMPTY_TAX },
    },
    itc_elg: {
      itc_avl: ITC_AVL_TYPES.map((ty) => emptyItc(ty)),
      itc_rev: [emptyItc("RUL"), emptyItc("OTH")],
      itc_net: [emptyItc("")],
      itc_inelg: [emptyItc("RUL"), emptyItc("OTH")],
    },
    inward_sup: {
      isup_details: [
        { ty: "GST", inter: "", intra: "" },
        { ty: "NONGST", inter: "", intra: "" },
      ],
    },
    intr_ltfee: {
      intr_details: { iamt: "", camt: "", samt: "", csamt: "" },
      ltfee_details: { camt: "", samt: "" },
    },
  };
}

function toNum(v: number | ""): number {
  if (v === "" || v == null) return 0;
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function taxToApi(t: Gstr3bTaxHeadFields): Record<string, number> {
  return {
    txval: toNum(t.txval),
    iamt: toNum(t.iamt),
    camt: toNum(t.camt),
    samt: toNum(t.samt),
    csamt: toNum(t.csamt),
  };
}

function itcToApi(rows: ItcRowProps[]): Record<string, unknown>[] {
  return rows.map((r) => ({
    ty: r.ty,
    iamt: toNum(r.iamt),
    camt: toNum(r.camt),
    samt: toNum(r.samt),
    csamt: toNum(r.csamt),
  }));
}

function singleItcToApi(row?: ItcRowProps): Record<string, number> {
  if (!row) return { iamt: 0, camt: 0, samt: 0, csamt: 0 };
  return {
    iamt: toNum(row.iamt),
    camt: toNum(row.camt),
    samt: toNum(row.samt),
    csamt: toNum(row.csamt),
  };
}

/** Build GSTN Save body from form state (integers as numbers). */
export function figuresToSaveBody(state: Gstr3bFiguresState): Record<string, unknown> {
  return {
    gstin: state.gstin.trim().toUpperCase(),
    ret_period: state.ret_period,
    sup_details: {
      osup_det: taxToApi(state.sup_details.osup_det),
      osup_zero: taxToApi(state.sup_details.osup_zero),
      osup_nil_exmp: taxToApi(state.sup_details.osup_nil_exmp),
      osup_nongst: taxToApi(state.sup_details.osup_nongst),
      isup_rev: taxToApi(state.sup_details.isup_rev),
    },
    itc_elg: {
      itc_avl: itcToApi(state.itc_elg.itc_avl),
      itc_rev: itcToApi(state.itc_elg.itc_rev),
      itc_net: singleItcToApi(state.itc_elg.itc_net[0]),
      itc_inelg: itcToApi(state.itc_elg.itc_inelg),
    },
    inward_sup: {
      isup_details: state.inward_sup.isup_details.map((r) => ({
        ty: r.ty,
        inter: toNum(r.inter),
        intra: toNum(r.intra),
      })),
    },
    intr_ltfee: {
      intr_details: {
        iamt: toNum(state.intr_ltfee.intr_details.iamt),
        camt: toNum(state.intr_ltfee.intr_details.camt),
        samt: toNum(state.intr_ltfee.intr_details.samt),
        csamt: toNum(state.intr_ltfee.intr_details.csamt),
      },
      ltfee_details: {
        camt: toNum(state.intr_ltfee.ltfee_details.camt),
        samt: toNum(state.intr_ltfee.ltfee_details.samt),
      },
    },
  };
}

export type OutwardSuggestion = {
  source: string;
  osup_det: Partial<Gstr3bTaxHeadFields>;
};

export type ItcOthSuggestion = {
  source: string;
  iamt?: number;
  camt?: number;
  samt?: number;
  csamt?: number;
};

/** Result of an explicit Load suggestions click (never auto-fetched). */
export type SuggestionLoadResult<T> =
  | { status: "available"; suggestion: T }
  | { status: "unavailable"; reason: string };
