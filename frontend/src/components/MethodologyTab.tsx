import React from 'react';
import { Calculator, ListChecks } from 'lucide-react';

export const MethodologyTab: React.FC = () => {
  return (
    <div className="tab-panel active">
      <div className="methodology-container">
        <div className="methodology-section">
          <h2>
            <Calculator size={22} style={{ marginRight: '0.5rem', verticalAlign: 'middle' }} />
            Smart Money Synergy Score (SMSS)
          </h2>
          <p>
            The SMSS is a quantitative rating out of 100 points combining
            financial quality, valuation, and corporate-network characteristics.
          </p>
          <p>
            The score is designed as a fundamental and ownership-network screening
            framework. It does not represent broker-level transactions, foreign flow,
            institutional trading activity, or a direct measure of "smart money" trades.
          </p>
        </div>

        <div className="methodology-section">
          <h2>
            <ListChecks size={22} style={{ marginRight: '0.5rem', verticalAlign: 'middle' }} />
            Score Weights and Criteria
          </h2>

          <div className="factor-list">
            <div className="factor-item">
              <div className="factor-score">40</div>
              <div className="factor-details">
                <h4>Financial Quality & Solvency (Max 40 points)</h4>
                <p>
                  Measures profitability and leverage using the latest available
                  financial data:
                </p>
                <ul>
                  <li>
                    <strong>Return on Equity (ROE)</strong>: ROE &ge; 20% (+15 pts),
                    &ge; 15% (+10 pts), &ge; 10% (+5 pts). ROE &lt; 0% applies a
                    10-point penalty.
                  </li>
                  <li>
                    <strong>Debt-to-Equity (D/E) Ratio</strong>: D/E &le; 0.5
                    (+15 pts), &le; 1.0 (+10 pts), &le; 2.0 (+5 pts). When the
                    ratio is unavailable or non-positive, the engine assigns
                    5 points.
                  </li>
                  <li>
                    <strong>Net Profit Margin (NPM)</strong>: NPM &ge; 20% (+10 pts),
                    &ge; 10% (+7 pts), &ge; 5% (+3 pts).
                  </li>
                </ul>
              </div>
            </div>

            <div className="factor-item">
              <div className="factor-score valuation">30</div>
              <div className="factor-details">
                <h4>Valuation Discounts (Max 30 points)</h4>
                <p>
                  Rewards lower positive earnings and book-value multiples based
                  on the latest available market price and financial data.
                </p>
                <ul>
                  <li>
                    <strong>Price-to-Earnings (P/E) Ratio</strong>: Positive P/E
                    &lt; 10 (+15 pts), 10 to 15 (+10 pts), 15 to 25 (+5 pts).
                  </li>
                  <li>
                    <strong>Price-to-Book (P/B) Ratio</strong>: PBV &lt; 1.0
                    (+15 pts), 1.0 to 1.5 (+10 pts), 1.5 to 3.0 (+5 pts).
                  </li>
                </ul>
              </div>
            </div>

            <div className="factor-item">
              <div className="factor-score network">30</div>
              <div className="factor-details">
                <h4>Corporate Network & Ownership (Max 30 points)</h4>
                <p>
                  Measures selected board, shareholder, and controlling-owner
                  relationships found in the available corporate network data.
                </p>
                <ul>
                  <li>
                    <strong>Blue-Chip Bridge (+12 points)</strong>: Added when at
                    least one director or commissioner is also connected to another
                    company in the engine's predefined Blue Chip list.
                  </li>
                  <li>
                    <strong>Shareholder Network Alignment (+10 points)</strong>:
                    Added when a non-corporate shareholder identified by the engine
                    as a Super Insider holds at least 1.0% of the company. Super
                    Insider identification is based on estimated portfolio value,
                    multi-company holdings, and/or board connections in the
                    underlying network data.
                  </li>
                  <li>
                    <strong>Conglomerate Strength (+8 points)</strong>: Added when
                    a corporate shareholder controls at least two companies and the
                    average ROE of the identified controlled companies is at least
                    15%.
                  </li>
                </ul>
              </div>
            </div>
          </div>
        </div>

        <div className="methodology-section">
          <h2>Important Interpretation</h2>
          <p>
            SMSS is a composite screening score based on financial, valuation,
            shareholder, board, and corporate-network data. A high SMSS score
            should not be interpreted as evidence of broker-level accumulation,
            institutional buying, foreign buying, or a guaranteed investment
            outcome.
          </p>
        </div>
      </div>
    </div>
  );
};
