/**
 * Barter overlay.
 *
 * Ported from Design_files/ui_kits/clockwork-world/Screens.jsx::TradeScreen:
 * the two columns, what you could sell and what they offer.
 *
 * IMPORTANT: this screen is presentation only. It reads prices from
 * /api/trade (data/economy.yaml), and each row's button presses ONE `buy` or
 * `sell` INTENT (v0.25.0 §7.3, §8.1): the pair comes from `GET
 * /api/intents/overlay`, core emits it as `overlay_action`, and the engine
 * re-checks it under the turn lock and runs its `trade` skill before the
 * narrator speaks (rule 1). There is no client-side transaction here and there
 * must not be -- an overlay that moved items itself would be a second,
 * disagreeing economy.
 *
 * The balance beam and "Strike the bargain" are retired: one turn carries one
 * intent, so a basket of several things struck at once has no engine verb (a
 * NOT WIRED row in docs/GOVERNANCE.md, spec §14). A row the server does not
 * list (a price you cannot meet, a thing they will not take, a trader you have
 * not met yet, whose counter the route names only by role) is drawn and not
 * pressable.
 */
import React, { useEffect, useState } from "react";
import Modal from "@core/parts/Modal.jsx";
import { fetchTrade } from "@core/api.js";
import { overlayTurnKey, useOverlayIntents } from "@core/hooks/useOverlayIntents.js";
import ActionButton, { SceneOwnsTurn } from "../parts/ActionButton.jsx";

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

function Row({ item, children }) {
  return (
    <div className="barter">
      <span className="barter__icon">
        {item.image ? <img src={item.image} alt="" /> : <span className="barter__blank" />}
      </span>
      <span className="barter__name">
        {item.name}
        {item.qty > 1 && <span className="barter__qty">×{item.qty}</span>}
      </span>
      {children}
    </div>
  );
}

export default function Trade({ state, sessionId, busy, onAct, onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [vendorIndex, setVendorIndex] = useState(0);
  const { offer } = useOverlayIntents(sessionId, overlayTurnKey(state));
  const turn = state?.world?.turn_number;

  // Prices and stock move with the turn, as the offer does.
  useEffect(() => {
    let live = true;
    fetchTrade(sessionId)
      .then((next) => live && setData(next))
      .catch(() => live && setError("Nobody answers."));
    return () => {
      live = false;
    };
  }, [sessionId, turn]);

  const vendor = data?.vendors?.[vendorIndex] || null;
  const gold = Number(data?.gold) || 0;
  // A stranger's counter is named by role and an opaque id until met (`trade_offer`), so no pair matches it.
  const stranger = vendor && !vendor.known ? "Not until you have spoken: they do not know you yet." : "";

  function press(intent) {
    onAct(intent);
    onClose();
  }

  return (
    <Modal
      title="Barter"
      onClose={onClose}
      footer={
        vendor && (
          <button type="button" className="btn btn--ghost" onClick={onClose}>
            Step back
          </button>
        )
      }
    >
      <SceneOwnsTurn offer={offer} />
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
              onClick={() => setVendorIndex(index)}
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
              <p className="overlay__kicker">You could sell</p>
              {vendor.buys.length === 0 && (
                <p className="overlay__empty">Nothing you carry interests them.</p>
              )}
              {vendor.buys.map((item) => (
                <Row key={item.id} item={item}>
                  <ActionButton offer={offer} action="sell" target={`${vendor.npc_id}/${item.id}`}
                    busy={busy} onAct={press} why={stranger || "They buy none of it."}>
                    Sell · {item.price}c
                  </ActionButton>
                </Row>
              ))}
            </div>

            <div>
              <p className="overlay__kicker">{vendor.name} offers</p>
              {vendor.sells.length === 0 && (
                <p className="overlay__empty">Their stock is bare.</p>
              )}
              {vendor.sells.map((item) => (
                <Row key={item.id} item={item}>
                  <ActionButton offer={offer} action="buy" target={`${vendor.npc_id}/${item.id}`}
                    busy={busy} onAct={press} why={stranger || "Not affordable."}>
                    Buy · {item.price}c
                  </ActionButton>
                </Row>
              ))}
            </div>
          </div>
          <p className="barter__hint">One thing at a time: each press is a turn.</p>
        </>
      )}
    </Modal>
  );
}
