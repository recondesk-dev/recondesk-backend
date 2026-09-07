import assert from "node:assert/strict";
import { describe, it } from "node:test";
import React from "react";
import ReactDOMServer from "react-dom/server";
import { ItcIneligibleBadge } from "./ItcIneligibleBadge.ts";

describe("ItcIneligibleBadge", () => {
  it("renders amber badge when itcAvailable is false", () => {
    const markup = ReactDOMServer.renderToStaticMarkup(
      React.createElement(ItcIneligibleBadge, { itcAvailable: false })
    );
    assert.match(markup, /ITC Ineligible/);
    assert.match(markup, /title="Marked ineligible in GSTR-2B"/);
    assert.match(markup, /bg-amber-50/);
    assert.match(markup, /text-amber-700/);
  });

  it("renders custom itcReason in title tooltip when provided", () => {
    const markup = ReactDOMServer.renderToStaticMarkup(
      React.createElement(ItcIneligibleBadge, {
        itcAvailable: false,
        itcReason: "Section 17(5) motor vehicles",
      })
    );
    assert.match(markup, /ITC Ineligible/);
    assert.match(markup, /title="Section 17\(5\) motor vehicles"/);
  });

  it("renders nothing when itcAvailable is true", () => {
    const markup = ReactDOMServer.renderToStaticMarkup(
      React.createElement(ItcIneligibleBadge, { itcAvailable: true })
    );
    assert.equal(markup, "");
  });

  it("renders nothing when itcAvailable is undefined or null", () => {
    const markup1 = ReactDOMServer.renderToStaticMarkup(
      React.createElement(ItcIneligibleBadge, { itcAvailable: undefined })
    );
    assert.equal(markup1, "");

    const markup2 = ReactDOMServer.renderToStaticMarkup(
      React.createElement(ItcIneligibleBadge, { itcAvailable: null })
    );
    assert.equal(markup2, "");
  });
});
