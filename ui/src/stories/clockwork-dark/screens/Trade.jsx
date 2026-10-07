/**
 * Barter overlay.
 *
 * Ported from Design_files/ui_kits/clockwork-world/Screens.jsx::TradeScreen —
 * the two columns, the balance beam, and "Strike the bargain" disabled while
 * you are short.
 *
 * IMPORTANT: this screen is presentation only. It reads prices from
 * /api/trade (data/economy.yaml) and then sends the bargain as the player's
 * TYPED words. There is no client-side transaction here and there must not be
 * -- an overlay that moved items itself would be a second, disagreeing economy.
 *
 * NOT WIRED (docs/GOVERNANCE.md, v0.21.0 final review finding 9): typed text
 * carries no intent, so no `trade` skill runs from it. Outside LM Studio's
 * `llm.mcp` mode only the narrator reads the bargain, and the prose can tell
 * of a trade the save never made. The intent path (an overlay hands `onAct`
 * an `{action, target}` the server checks against `legal_intents`) is the
 * v0.23.0 flagship overhaul's.
 */
import React, { useEffect, useMemo, useState } from "react";
import Modal from "@core/parts/Modal.jsx";
import { fetchTrade } from "@core/api.js";

/**
 * A trader's tab: its name, numbered when two traders share it -- two
 * strangers of one role ("the baker") read as identical tabs otherwise
 * (T3 re-review R4).
 */
export function tabLabel(vendors, index) {
  const name = vendors[index]?.name || "";
  const same = vendors.filter((v) => (v?.name || "") === name).length;
  if (same < 2) return name;
  const nth = vendors.slice(0, index + 1).filter((v) => (v?.name || "") === name).length;
  return `${name} (${nth})`;
}

function Row({ item, on, onToggle }) {
  const worth = (Number(item.price) || 0) * (Number(item.qty) || 1);

  return (
    <button
      type="button"
      className={`barter ${on ? "is-on" : ""}`}
      onClick={onToggle}
      aria-pressed={on}
    >
      <span className="barter__icon">
        {item.image ? <img src={item.image} alt="" /> : <span className="barter__blank" />}
      </span>
      <span className="barter__name">
        {item.name}
        {item.qty > 1 && <span className="barter__qty">×{item.qty}</span>}
      </span>
      <span className="barter__worth">{worth}c</span>
    </button>
  );
}

export default function Trade({ sessionId, busy, onStrike, onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [vendorIndex, setVendorIndex] = useState(0);
  const [offered, setOffered] = useState({});
  const [wanted, setWanted] = useState({});

  useEffect(() => {
    let live = true;
    fetchTrade(sessionId)
      .then((next) => live && setData(next))
      .catch(() => live && setError("Nobody answers."));
    return () => {
      live = false;
    };
  }, [sessionId]);

  const vendor = data?.vendors?.[vendorIndex] || null;
  const gold = Number(data?.gold) || 0;

  const { giveTotal, getTotal, giving, getting } = useMemo(() => {
    const giving = (vendor?.buys || []).filter((i) => offered[i.id]);
    const getting = (vendor?.sells || []).filter((i) => wanted[i.id]);
    return {
      giving,
      getting,
      giveTotal: giving.reduce((sum, i) => sum + i.price * (i.qty || 1), 0),
      getTotal: getting.reduce((sum, i) => sum + i.price, 0),
    };
  }, [vendor, offered, wanted]);

  // Coin counts on the give side: the engine's trade skill settles in gold,
  // so a purse you can actually reach is part of what you are offering.
  const balance = gold + giveTotal - getTotal;
  const short = balance < 0;
  const nothingChosen = giving.length === 0 && getting.length === 0;

  function strike() {
    const parts = [];
    if (getting.length) parts.push(`buy ${getting.map((i) => i.name).join(", ")}`);
    if (giving.length)
      parts.push(
        `sell ${giving.map((i) => (i.qty > 1 ? `${i.name} ×${i.qty}` : i.name)).join(", ")}`
      );
    onStrike(`You barter with ${vendor.name}: ${parts.join("; ")}.`);
    onClose();
  }

  const swing = getTotal > 0 ? Math.min(100, (Math.abs(balance) / getTotal) * 50) : 0;

  return (
    <Modal
      title="Barter"
      onClose={onClose}
      footer={
        vendor && (
          <>
            <button type="button" className="btn btn--ghost" onClick={onClose}>
              Step back
            </button>
            <button
              type="button"
              className="btn"
              disabled={short || nothingChosen || busy}
              onClick={strike}
            >
              Strike the bargain
            </button>
          </>
        )
      }
    >
      {error && <p className="overlay__error">{error}</p>}
      {!data && !error && <p className="overlay__empty">Looking around…</p>}

      {data && data.vendors.length === 0 && (
        <p className="overlay__empty">Nobody here trades in anything you have.</p>
      )}

      {data && data.vendors.length > 1 && (
        <div className="codextabs" role="group" aria-label="Traders">
          {data.vendors.map((v, index) => (
            <button
              key={v.npc_id}
              type="button"
              aria-pressed={index === vendorIndex}
              className={`codextab ${index === vendorIndex ? "is-active" : ""}`}
              onClick={() => {
                setVendorIndex(index);
                setOffered({});
                setWanted({});
              }}
            >
              {tabLabel(data.vendors, index)}
            </button>
          ))}
        </div>
      )}

      {vendor && (
        <>
          <p className="overlay__kicker">
            {vendor.name}
            {vendor.role ? ` · ${vendor.role}` : ""} · your purse {gold}c
          </p>

          <div className="barter__columns">
            <div>
              <p className="overlay__kicker">You give</p>
              {vendor.buys.length === 0 && (
                <p className="overlay__empty">Nothing you carry interests them.</p>
              )}
              {vendor.buys.map((item) => (
                <Row
                  key={item.id}
                  item={item}
                  on={!!offered[item.id]}
                  onToggle={() => setOffered((o) => ({ ...o, [item.id]: !o[item.id] }))}
                />
              ))}
              <p className="barter__hint">Tap to add or hold back.</p>
            </div>

            <div>
              <p className="overlay__kicker">{vendor.name} offers</p>
              {vendor.sells.length === 0 && (
                <p className="overlay__empty">Their stock is bare.</p>
              )}
              {vendor.sells.map((item) => (
                <Row
                  key={item.id}
                  item={item}
                  on={!!wanted[item.id]}
                  onToggle={() => setWanted((w) => ({ ...w, [item.id]: !w[item.id] }))}
                />
              ))}
            </div>
          </div>

          <div className="beam">
            <div className="beam__row">
              <span className="beam__label">Balance</span>
              <span className={`beam__value ${short ? "is-short" : "is-fair"}`} role="status">
                {short
                  ? `${Math.abs(balance)}c short`
                  : nothingChosen
                    ? "Nothing agreed yet"
                    : vendor.known
                      ? `Fair — ${vendor.name.split(" ")[0]} nods`
                      : /* A stranger is "the <role>" (v0.21.0): no first name to nod. */
                        "Fair — a nod"}
              </span>
            </div>
            <div className="beam__track">
              <span className="beam__pivot" aria-hidden="true" />
              <span
                className={`beam__weight ${short ? "is-short" : "is-fair"}`}
                style={short ? { right: "50%", width: `${swing}%` } : { left: "50%", width: `${swing}%` }}
              />
            </div>
          </div>
        </>
      )}
    </Modal>
  );
}
