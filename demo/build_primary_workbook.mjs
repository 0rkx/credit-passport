import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const sourceDir = "/Users/owaiskhan/Desktop/Credit Passport Upload Files/Anika Updates";
const output = "/Users/owaiskhan/Desktop/Credit Passport Test.xlsx";

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

async function importBook(name) {
  return SpreadsheetFile.importXlsx(await FileBlob.load(path.join(sourceDir, name)));
}

function styleTransactionSheet(sheet, accent, tableName) {
  const rows = 25;
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(1);
  sheet.getRange(`A1:L${rows}`).format.font = { name: "Aptos", size: 10, color: "#22313f" };
  sheet.getRange("A1:L1").format = {
    fill: accent,
    font: { name: "Aptos", size: 10, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "all", style: "thin", color: accent },
  };
  sheet.getRange(`A2:L${rows}`).format.borders = { preset: "inside", style: "thin", color: "#D7E0E8" };
  sheet.getRange(`C2:C${rows}`).format.numberFormat = "#,##0";
  sheet.getRange(`H2:H${rows}`).format.numberFormat = "#,##0;[Red]-#,##0";
  sheet.getRange(`L2:L${rows}`).format.numberFormat = "0";
  sheet.getRange(`A1:L${rows}`).format.rowHeight = 21;
  sheet.getRange("A1:L1").format.rowHeight = 32;
  [13, 18, 13, 10, 11, 22, 32, 16, 13, 13, 16, 16].forEach((width, index) => {
    sheet.getRangeByIndexes(0, index, rows, 1).format.columnWidth = width;
  });
  sheet.tables.add(`A1:L${rows}`, true, tableName);
  sheet.getRange(`E2:E${rows}`).dataValidation = { rule: { type: "list", values: ["credit", "debit"] } };
  sheet.getRange(`K2:K${rows}`).dataValidation = { rule: { type: "list", values: ["received", "paid", "late", "income-reduced"] } };
  sheet.getRange("A1").note = "Keep this header row unchanged. Edit the rows below, save the workbook, then upload it as one new evidence source.";
  sheet.getRange("C1").note = "Use a positive number for amount. Use direction=debit for outflows; do not type negative amounts.";
  sheet.getRange("K1").note = "Use paid or late for obligations. due_on, paid_on and days_past_due show payment timing.";
}

function copySheetValues(source, target) {
  const values = source.getRange("A1:L25").values;
  target.getRange("A1:L25").values = [headers, ...values.slice(1)];
}

const positiveBook = await importBook("Anika-positive-update.xlsx");
const adverseBook = await importBook("Anika-adverse-update.xlsx");
const mixedBook = await importBook("Anika-mixed-update.xlsx");

const workbook = positiveBook;
const transactions = workbook.worksheets.getItem("Transactions");
styleTransactionSheet(transactions, "#087f5b", "CreditPassportTestTransactions");

const adverse = workbook.worksheets.add("Adverse update");
copySheetValues(adverseBook.worksheets.getItem("Transactions"), adverse);
styleTransactionSheet(adverse, "#b42318", "CreditPassportTestAdverse");

const mixed = workbook.worksheets.add("Mixed update");
copySheetValues(mixedBook.worksheets.getItem("Transactions"), mixed);
styleTransactionSheet(mixed, "#a15c00", "CreditPassportTestMixed");

const guide = workbook.worksheets.getItem("How to use");
guide.getRange("A1").values = [["Credit Passport Test"]];
guide.getRange("A3").values = [["One editable transaction workbook for testing how evidence changes the passport score."]];
guide.getRange("A5:B12").values = [
  ["1", "Upload Transactions as-is to show a positive update."],
  ["2", "To show an adverse update, copy rows A2:L25 from Adverse update and paste over Transactions A2:L25, then save and upload."],
  ["3", "To show a mixed update, copy rows A2:L25 from Mixed update and paste over Transactions A2:L25, then save and upload."],
  ["4", "Keep the header row unchanged. Use a positive amount; set direction=debit for outflows."],
  ["5", "Use event_type, due_on, paid_on, status and days_past_due to describe payment behaviour."],
  ["6", "Create a fresh Anika applicant for each before/after comparison; uploads add records and do not remove earlier ones."],
  ["7", "Switching credit products changes the weighting of the same observed evidence."],
  ["8", "The parser ignores uploaded score/risk columns and recalculates from transaction evidence."],
];
guide.getRange("A14").values = [["The Transactions sheet is the only sheet to upload. The other sheets are ready-to-copy alternatives."]];
guide.getRange("A15").values = [["All rows are fictional INR values prepared for a live walkthrough."]];
guide.getRange("A1:F1").format = { fill: "#087f5b", font: { name: "Aptos", size: 16, bold: true, color: "#FFFFFF" }, verticalAlignment: "center" };
guide.getRange("A3:F3").format = { font: { name: "Aptos", size: 11, italic: true, color: "#52657A" }, wrapText: true };
guide.getRange("A5:A12").format = { fill: "#EEF3F7", font: { name: "Aptos", size: 11, bold: true, color: "#087f5b" }, horizontalAlignment: "center" };
guide.getRange("B5:B12").format.wrapText = true;
guide.getRange("A14:F14").format = { fill: "#FFF8E8", font: { name: "Aptos", size: 10, color: "#7A4E00" }, wrapText: true };
guide.getRange("A15:F15").format = { font: { name: "Aptos", size: 10, italic: true, color: "#718198" } };
guide.getRange("A5:B12").format.rowHeight = 30;
guide.getRange("B:B").format.columnWidth = 92;

workbook.recalculate();
const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(output);
console.log(output);
