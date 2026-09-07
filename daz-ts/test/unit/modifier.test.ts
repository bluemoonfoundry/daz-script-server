import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazModifier } from "../../src/modifier.js";
import { DazMorph } from "../../src/morph.js";
import { DazDForce } from "../../src/dforce.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

afterEach(() => vi.unstubAllGlobals());

function stub(value: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ success: true, result: value, output: [], request_id: "r", duration_ms: 0 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("DazModifier", () => {
  it("modifierLabel reads via getLabel()", async () => {
    const fetchMock = stub("Test Modifier");
    const mod = new DazModifier(new DazClient({ token: "" }), "MODLOC");
    const result = await mod.modifierLabel();
    expect(result).toBe("Test Modifier");
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe("(function(){\nvar m = MODLOC; return m ? m.getLabel() : null;\n})()");
  });

  it("enabled getter reads via isEnabled()", async () => {
    const fetchMock = stub(true);
    const mod = new DazModifier(new DazClient({ token: "" }), "MODLOC");
    const result = await mod.enabled();
    expect(result).toBe(true);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe("(function(){\nvar m = MODLOC; return m ? m.isEnabled() : null;\n})()");
  });

  it("setEnabled writes via setEnabled(false)", async () => {
    const fetchMock = stub(null);
    const mod = new DazModifier(new DazClient({ token: "" }), "MODLOC");
    await mod.setEnabled(false);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe("(function(){\nvar m = MODLOC; if (m) m.setEnabled(false);\n})()");
  });

  it("setEnabled writes via setEnabled(true)", async () => {
    const fetchMock = stub(null);
    const mod = new DazModifier(new DazClient({ token: "" }), "MODLOC");
    await mod.setEnabled(true);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe("(function(){\nvar m = MODLOC; if (m) m.setEnabled(true);\n})()");
  });
});

describe("DazMorph", () => {
  it("value getter reads via getValueChannel().getValue()", async () => {
    const fetchMock = stub(0.75);
    const morph = new DazMorph(new DazClient({ token: "" }), "MORPHLOC");
    const result = await morph.value();
    expect(result).toBe(0.75);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe("(function(){\nvar m = MORPHLOC; return m ? m.getValueChannel().getValue() : null;\n})()");
  });

  it("setValue writes via getValueChannel().setValue()", async () => {
    const fetchMock = stub(null);
    const morph = new DazMorph(new DazClient({ token: "" }), "MORPHLOC");
    await morph.setValue(0.75);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe("(function(){\nvar m = MORPHLOC; if (m) m.getValueChannel().setValue(0.75);\n})()");
  });

  it("min reads via getValueChannel().getMin()", async () => {
    const fetchMock = stub(0.0);
    const morph = new DazMorph(new DazClient({ token: "" }), "MORPHLOC");
    const result = await morph.min();
    expect(result).toBe(0.0);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe("(function(){\nvar m = MORPHLOC; return m ? m.getValueChannel().getMin() : null;\n})()");
  });

  it("max reads via getValueChannel().getMax()", async () => {
    const fetchMock = stub(1.0);
    const morph = new DazMorph(new DazClient({ token: "" }), "MORPHLOC");
    const result = await morph.max();
    expect(result).toBe(1.0);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toBe("(function(){\nvar m = MORPHLOC; return m ? m.getValueChannel().getMax() : null;\n})()");
  });
});

describe("DazDForce", () => {
  it("freezeSimulation reads the 'Freeze Simulation' property by label", async () => {
    const fetchMock = stub(true);
    const dforce = new DazDForce(new DazClient({ token: "" }), "DFLOC");
    const result = await dforce.freezeSimulation();
    expect(result).toBe(true);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain('findPropertyByLabel("Freeze Simulation")');
  });

  it("setFreezeSimulation(true) delegates to freeze via setValue", async () => {
    const fetchMock = stub(null);
    const dforce = new DazDForce(new DazClient({ token: "" }), "DFLOC");
    await dforce.setFreezeSimulation(true);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("p.setValue(true)");
  });

  it("setFreezeSimulation(false) delegates via setValue", async () => {
    const fetchMock = stub(null);
    const dforce = new DazDForce(new DazClient({ token: "" }), "DFLOC");
    await dforce.setFreezeSimulation(false);
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("p.setValue(false)");
  });

  it("freeze() delegates to setFreezeSimulation(true)", async () => {
    const fetchMock = stub(null);
    const dforce = new DazDForce(new DazClient({ token: "" }), "DFLOC");
    await dforce.freeze();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("p.setValue(true)");
  });

  it("unfreeze() delegates to setFreezeSimulation(false)", async () => {
    const fetchMock = stub(null);
    const dforce = new DazDForce(new DazClient({ token: "" }), "DFLOC");
    await dforce.unfreeze();
    const script = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(script).toContain("p.setValue(false)");
  });
});
