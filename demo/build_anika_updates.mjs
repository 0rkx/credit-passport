import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "/Users/owaiskhan/Desktop/Credit Passport Upload Files/Anika Updates";
const font = "Aptos";
const headers = [
  "date",
  "event_type",
  "amount",
  "currency",
  "direction",
  "reference",
  "description",
  "balance_after",
  "due_on",
  "paid_on",
  "status",
  "days_past_due",
];

const row = ({
  date,
  event_type,
  amount,
  direction,
  reference,
  description,
  balance_after,
  due_on = "",
  paid_on = "",
  status,
  days_past_due = "",
}) => [
  date,
  event_type,
  amount,
  "INR",
  direction,
  reference,
  description,
  balance_after,
  due_on,
  paid_on,
  status,
  days_past_due,
];

function positiveRows() {
  const rows = [];
  const days = ["28", "29", "30"];
  for (let index = 0; index < 24; index += 1) {
    const cycle = Math.floor(index / 6);
    const day = days[index % 3];
    const date = `2026-06-${day}`;
    const event = ["salary", "platform_earnings", "deposit", "rent", "remittance", "insurance"][index % 6];
    const amounts = {
      salary: 220000 + cycle * 5000,
      platform_earnings: 20000 + cycle * 1000,
      deposit: 30000 + cycle * 2000,
      rent: 42000 + cycle * 1000,
      remittance: 45000 + cycle * 2000,
      insurance: 4500 + cycle * 100,
    };
    const credit = ["salary", "platform_earnings", "deposit", "remittance"].includes(event);
    const balance = 800000 + index * 15000;
    const scheduled = ["rent", "insurance"].includes(event);
    rows.push(row({
      date,
      event_type: event,
      amount: amounts[event],
      direction: credit ? "credit" : "debit",
      reference: `ANIKA-POS-${String(index + 1).padStart(2, "0")}`,
      description:
        event === "salary"
          ? "Salary credit"
          : event === "platform_earnings"
            ? "Platform earnings received"
            : event === "deposit"
              ? "Reserve deposit"
              : event === "remittance"
                ? "Inbound remittance received"
                : event === "rent"
                  ? "Rent paid on time"
                  : "Protection premium paid on time",
      balance_after: balance,
      due_on: scheduled ? date : "",
      paid_on: scheduled ? date : "",
      status: credit ? "received" : "paid",
      days_past_due: scheduled ? 0 : "",
    }));
  }
  return rows;
}

function adverseRows() {
  const rows = [];
  const salaries = [60000, 55000, 50000, 45000, 40000, 35000];
  for (let index = 0; index < 24; index += 1) {
    const cycle = Math.floor(index / 4);
    const day = ["28", "29", "30"][index % 3];
    const date = `2026-06-${day}`;
    const event = ["salary", "rent", "utility", "loan_payment"][index % 4];
    const amounts = {
      salary: salaries[cycle],
      rent: 140000 + cycle * 4000,
      utility: 80000 + cycle * 3000,
      loan_payment: 120000 + cycle * 5000,
    };
    const balance = -100000 - index * 25000;
    const salary = event === "salary";
    rows.push(row({
      date,
      event_type: event,
      amount: amounts[event],
      direction: salary ? "credit" : "debit",
      reference: `ANIKA-ADV-${String(index + 1).padStart(2, "0")}`,
      description: salary
        ? "Reduced contract pay"
        : event === "rent"
          ? "Rent paid late"
          : event === "utility"
            ? "Utility paid late"
            : "Loan payment paid late",
      balance_after: balance,
      due_on: salary ? "" : "2026-06-27",
      paid_on: salary ? "" : date,
      status: salary ? "income-reduced" : "late",
      days_past_due: salary ? "" : 1 + (index % 3),
    }));
  }
  return rows;
}

function mixedRows() {
  const rows = [];
  const days = ["28", "29", "30"];
  for (let index = 0; index < 24; index += 1) {
    const cycle = Math.floor(index / 6);
    const day = days[index % 3];
    const date = `2026-06-${day}`;
    const event = ["salary", "platform_earnings", "deposit", "rent", "remittance", "utility"][index % 6];
    const amounts = {
      salary: 180000 + cycle * 3000,
      platform_earnings: 15000 + cycle * 1000,
      deposit: 8000 + cycle * 500,
      rent: 60000 + cycle * 2500,
      remittance: 25000 + cycle * 1500,
      utility: 12000 + cycle * 500,
    };
    const credit = ["salary", "platform_earnings", "deposit", "remittance"].includes(event);
    const scheduled = ["rent", "utility"].includes(event);
    const late = scheduled && cycle % 2 === 0;
    const due = scheduled ? (late ? "2026-06-27" : date) : "";
    const paid = scheduled ? date : "";
    rows.push(row({
      date,
      event_type: event,
      amount: amounts[event],
      direction: credit ? "credit" : "debit",
      reference: `ANIKA-MIX-${String(index + 1).padStart(2, "0")}`,
      description: credit
        ? event === "salary"
          ? "Salary credit"
          : event === "platform_earnings"
            ? "Variable platform earnings"
            : event === "deposit"
              ? "Small reserve deposit"
              : "Inbound remittance received"
        : late
          ? `${event === "rent" ? "Rent" : "Utility"} paid late`
          : `${event === "rent" ? "Rent" : "Utility"} paid on time`,
      balance_after: 600000 - index * 6000,
      due_on: due,
      paid_on: paid,
      status: credit ? "received" : late ? "late" : "paid",
      days_past_due: scheduled ? (late ? 1 + cycle : 0) : "",
    }));
  }
  return rows;
}

const variants = [
  {
    file: "Anika-positive-update.xlsx",
    title: "Anika Mehta - Positive financial update",
    subtitle: "Recent records with stable income, reserves, cross-border support and on-time commitments.",
    rows: positiveRows(),
    accent: "#087f5b",
  },
  {
    file: "Anika-adverse-update.xlsx",
    title: "Anika Mehta - Adverse financial update",
    subtitle: "Recent records with reduced income, late obligations and negative balances.",
    rows: adverseRows(),
    accent: "#b42318",
  },
  {
    file: "Anika-mixed-update.xlsx",
    title: "Anika Mehta - Mixed financial update",
    subtitle: "Recent records with variable income, small reserves and a mix of on-time and late payments.",
    rows: mixedRows(),
    accent: "#a15c00",
  },
];

function formatSheet(sheet, variant) {
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(1);
  const totalRows = variant.rows.length + 1;
  const all = sheet.getRange(`A1:L${totalRows}`);
  all.format.font = { name: font, size: 10, color: "#22313f" };
  all.format.verticalAlignment = "center";
  all.format.wrapText = false;
  sheet.getRange("A1:L1").format = {
    fill: variant.accent,
    font: { name: font, size: 10, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "all", style: "thin", color: variant.accent },
  };
  sheet.getRange(`A2:L${totalRows}`).format.borders = { preset: "inside", style: "thin", color: "#D7E0E8" };
  sheet.getRange(`A2:A${totalRows}`).format.numberFormat = "@";
  sheet.getRange(`C2:C${totalRows}`).format.numberFormat = "#,##0";
  sheet.getRange(`H2:H${totalRows}`).format.numberFormat = "#,##0;[Red]-#,##0";
  sheet.getRange(`L2:L${totalRows}`).format.numberFormat = "0";
  sheet.getRange(`A1:L${totalRows}`).format.rowHeight = 21;
  sheet.getRange("A1:L1").format.rowHeight = 32;
  const widths = [13, 18, 13, 10, 11, 22, 32, 16, 13, 13, 16, 16];
  widths.forEach((width, index) => sheet.getRangeByIndexes(0, index, totalRows, 1).format.columnWidth = width);
  sheet.tables.add(`A1:L${totalRows}`, true, `${variant.file.replace(/[^A-Za-z0-9]/g, "").slice(0, 20)}Table`);
  sheet.getRange(`E2:E${totalRows}`).dataValidation = { rule: { type: "list", values: ["credit", "debit"] } };
  sheet.getRange(`B2:B${totalRows}`).dataValidation = {
    rule: {
      type: "list",
      values: ["salary", "platform_earnings", "deposit", "rent", "utility", "remittance", "insurance", "loan_payment"],
    },
  };
  sheet.getRange(`K2:K${totalRows}`).dataValidation = {
    rule: {
      type: "list",
      values: ["received", "paid", "late", "income-reduced"],
    },
  };
  sheet.getRange("A1").note = "Keep this header row unchanged. Edit the rows below, save the workbook, then upload it as one new evidence source.";
  sheet.getRange("C1").note = "Use a positive number for amount. Use direction=debit for outflows; do not type negative amounts.";
  sheet.getRange("K1").note = "Use paid or late for obligations. due_on, paid_on and days_past_due show payment timing.";
}

async function buildVariant(variant) {
  const workbook = Workbook.create();
  const tx = workbook.worksheets.add("Transactions");
  tx.getRange(`A1:L${variant.rows.length + 1}`).values = [headers, ...variant.rows];
  formatSheet(tx, variant);
  const guide = workbook.worksheets.add("How to use");
  guide.showGridLines = false;
  guide.getRange("A1:F16").format.font = { name: font, size: 11, color: "#22313f" };
  guide.getRange("A1:F1").merge();
  guide.getRange("A1").values = [[variant.title]];
  guide.getRange("A1:F1").format = {
    fill: variant.accent,
    font: { name: font, size: 16, bold: true, color: "#FFFFFF" },
    verticalAlignment: "center",
  };
  guide.getRange("A1:F1").format.rowHeight = 32;
  guide.getRange("A3:F3").merge();
  guide.getRange("A3").values = [[variant.subtitle]];
  guide.getRange("A3:F3").format = { font: { name: font, size: 11, italic: true, color: "#52657A" }, wrapText: true };
  guide.getRange("A5:B12").values = [
    ["1", "Open Transactions and edit only the rows below the header."],
    ["2", "Keep amount positive; use direction=credit for inflow and direction=debit for outflow."],
    ["3", "Use ISO dates (YYYY-MM-DD). For obligations, keep due_on and paid_on to show timing."],
    ["4", "Use a clear event_type such as salary, rent, utility, loan_payment or deposit."],
    ["5", "Save the workbook, then upload it as one new evidence source for Anika Mehta."],
    ["6", "Upload a fresh applicant for each comparison; uploads add records and do not remove earlier ones."],
    ["7", "Product scores can differ because each product weights the same observed evidence differently."],
    ["8", "A larger amount is not automatically good or bad; direction, event type, timing and balance drive the result."],
  ];
  guide.getRange("A5:A12").format = { fill: "#EEF3F7", font: { name: font, size: 11, bold: true, color: variant.accent }, horizontalAlignment: "center" };
  guide.getRange("B5:B12").format.wrapText = true;
  guide.getRange("A14:F14").merge();
  guide.getRange("A14").values = [["The file is intentionally editable. Keep the column names and save as .xlsx before uploading."]];
  guide.getRange("A14:F14").format = { fill: "#FFF8E8", font: { name: font, size: 10, color: "#7A4E00" }, wrapText: true };
  guide.getRange("A15:F15").merge();
  guide.getRange("A15").values = [["All records are fictional INR values prepared for a product walkthrough."]];
  guide.getRange("A15:F15").format = { font: { name: font, size: 10, italic: true, color: "#718198" } };
  guide.getRange("A1:F16").format.borders = { preset: "inside", style: "thin", color: "#E1E7ED" };
  guide.getRange("A:A").format.columnWidth = 6;
  guide.getRange("B:B").format.columnWidth = 86;
  guide.getRange("C:F").format.columnWidth = 14;
  guide.getRange("A5:B12").format.rowHeight = 26;
  workbook.recalculate();
  const out = await SpreadsheetFile.exportXlsx(workbook);
  await out.save(path.join(outputDir, variant.file));
}

await fs.mkdir(outputDir, { recursive: true });
for (const variant of variants) await buildVariant(variant);
console.log(JSON.stringify(variants.map((variant) => ({ file: variant.file, rows: variant.rows.length }))));
