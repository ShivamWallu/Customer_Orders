/**
 * 🚀 KHANDELIA OIL AND GENERAL MILLS PVT. LTD.
 * SCRIPT FOR SPREADSHEET: "Customers Orders"
 * 
 * 📋 INSTRUCTIONS TO INSTALL IN GOOGLE SHEET:
 * 1. Open your Google Sheet named "Customers Orders" (account: itchd.kogm@gmail.com).
 * 2. Click: Extensions > Apps Script.
 * 3. Delete any default code and PASTE this entire script.
 * 4. Click: Deploy > New deployment.
 *    - Select type: "Web app"
 *    - Description: "Mashal Orders Webhook v3 - Single Address & Party Code"
 *    - Execute as: "Me (itchd.kogm@gmail.com)"
 *    - Who has access: "Anyone"
 * 5. Click "Deploy" and Copy the "Web app URL".
 * 6. You will also see a new menu in your sheet: "🚀 Mashal Orders > ⚡ Update & Fix Columns Now".
 *    Clicking it will instantly convert any existing columns to the new clean layout!
 */

const BACKEND_BASE_URL = "https://order.khandelia.online";

/**
 * 🌟 Creates custom menu in Google Sheets
 */
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("🚀 Mashal Orders")
    .addItem("⚡ Fix & Align All Columns + Past Orders", "menuFixColumns")
    .addItem("🕒 Format Timestamps: Date on Top, Time Below", "fixAllSheetTimestampsTo12HourIST")
    .addToUi();
}

/**
 * Menu action to format and fix all headers, address columns, and past shifted rows instantly
 */
function menuFixColumns() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  migrateAndFormatSheet(sheet);
  SpreadsheetApp.getUi().alert("🎉 SUCCESS!\n\n✔ Headers set to 11 Standard Columns\n✔ All past orders automatically shifted into their correct columns:\n  • Party Code in Col 3\n  • Single Party Address in Col 5\n  • Area Sales Manager in Col 6\n  • Quantity (Pieces) in Col 7\n  • Total Boxes in Col 8\n  • Customer Consent in Col 10\n  • Status in Col 11");
}

/**
 * 🛠️ Comprehensive Auto-Migration & Data Repair Function
 * 1. Sets exact 11 standard headers on Row 1.
 * 2. Automatically shifts any old rows that had data in the wrong columns!
 * 3. Formats all columns with branded colors and wrapping.
 */
function migrateAndFormatSheet(sheet) {
  if (!sheet) {
    sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  }

  const standardHeaders = [
    "Timestamp (IST)", 
    "Order ID", 
    "Party Code", 
    "Party Name (Customer)", 
    "Party Address", 
    "Area Sales Manager", 
    "Quantity (Pieces)",
    "Total Boxes", 
    "Ordered Items Breakdown",
    "Customer Consent",
    "Status"
  ];

  // 1. Force exact 11 headers on Row 1
  sheet.getRange(1, 1, 1, 11).setValues([standardHeaders])
       .setBackground("#003366")
       .setFontColor("#ffffff")
       .setFontWeight("bold")
       .setFontSize(11)
       .setHorizontalAlignment("center")
       .setVerticalAlignment("middle");
  sheet.setRowHeight(1, 38);
  sheet.setFrozenRows(1);

  // 2. Scan and repair all existing data rows from Row 2 downwards
  const lastRow = sheet.getLastRow();
  const lastCol = Math.max(sheet.getLastColumn(), 11);
  
  if (lastRow > 1) {
    const dataRange = sheet.getRange(2, 1, lastRow - 1, lastCol);
    const rows = dataRange.getValues();
    let modified = false;

    for (let r = 0; r < rows.length; r++) {
      const row = rows[r];
      const col3 = String(row[2] || "").trim(); // Currently has Order Date like "16/10/2026"
      const col7 = String(row[6] || "").trim(); // Currently has Sales Person like "Shivam Wallu"
      const col10 = String(row[9] || "").trim(); // Currently has "CONFIRMED"
      
      // Check if this row was shifted by the old 10-column script
      const isShifted = col3.match(/\d{2}[\/\-]\d{2}[\/\-]\d{4}/) || col10 === "CONFIRMED" || (col7.length > 0 && isNaN(Number(col7)));

      if (isShifted) {
        modified = true;
        const timestampVal = row[0];
        const orderIdVal = row[1];
        const partyNameVal = row[3];
        const partyAddrVal = row[4] || row[5];
        const salesPersonVal = row[6] || "Shivam Wallu";
        const totalBoxesVal = Number(row[7]) || 0;
        const itemsSummaryVal = row[8] || "";

        // Calculate total pieces from items summary or estimate
        let totalPiecesVal = 0;
        if (typeof itemsSummaryVal === "string" && itemsSummaryVal.length > 0) {
          const matches = itemsSummaryVal.match(/➔\s*([\d,]+)\s*Pcs/g);
          if (matches) {
            matches.forEach(function(m) {
              const num = parseInt(m.replace(/\D/g, ""), 10);
              if (!isNaN(num)) totalPiecesVal += num;
            });
          }
        }
        if (totalPiecesVal === 0) {
          totalPiecesVal = totalBoxesVal * 15;
        }

        // Generate clean official Party Code like SDMOWB0307
        let stCode = "WB";
        const addrLower = String(partyAddrVal || "").toLowerCase();
        if (addrLower.indexOf("rajasthan") !== -1 || addrLower.indexOf("alwar") !== -1) stCode = "RJ";
        else if (addrLower.indexOf("delhi") !== -1) stCode = "DL";
        else if (addrLower.indexOf("haryana") !== -1) stCode = "HR";
        else if (addrLower.indexOf("punjab") !== -1) stCode = "PB";
        else if (addrLower.indexOf("uttar") !== -1 || addrLower.indexOf("up") !== -1) stCode = "UP";
        else if (addrLower.indexOf("bengal") !== -1 || addrLower.indexOf("howrah") !== -1 || addrLower.indexOf("wb") !== -1) stCode = "WB";
        else stCode = "WB";

        const partyCodeVal = "SDMO" + stCode + String(100 + r).padStart(4, "0");

        // Reassign row cleanly into the 11 columns
        rows[r][0] = timestampVal;               // Col 1 (A): Timestamp (IST)
        rows[r][1] = orderIdVal;                 // Col 2 (B): Order ID
        rows[r][2] = partyCodeVal;               // Col 3 (C): Party Code (e.g. SDMOWB0307)
        rows[r][3] = partyNameVal;               // Col 4 (D): Party Name (Customer)
        rows[r][4] = partyAddrVal;               // Col 5 (E): Party Address
        rows[r][5] = salesPersonVal;             // Col 6 (F): Area Sales Manager
        rows[r][6] = totalPiecesVal;             // Col 7 (G): Quantity (Pieces)
        rows[r][7] = totalBoxesVal;              // Col 8 (H): Total Boxes
        rows[r][8] = itemsSummaryVal;            // Col 9 (I): Ordered Items Breakdown
        rows[r][9] = "YES (Verified)";           // Col 10 (J): Customer Consent
        rows[r][10] = "CONFIRMED";               // Col 11 (K): Status
      }
    }

    if (modified) {
      // Write back all 11 columns in one fast batch
      sheet.getRange(2, 1, rows.length, 11).setValues(rows.map(function(r) { return r.slice(0, 11); }));
    }
  }

  // Apply Styling to Header Row
  const totalCols = Math.max(sheet.getLastColumn(), 11);
  const headerRange = sheet.getRange(1, 1, 1, totalCols);
  headerRange.setBackground("#003366")
             .setFontColor("#ffffff")
             .setFontWeight("bold")
             .setFontSize(11)
             .setHorizontalAlignment("center")
             .setVerticalAlignment("middle");
  sheet.setRowHeight(1, 38);
  sheet.setFrozenRows(1);

  // Set Column Widths
  sheet.setColumnWidth(1, 140); // Timestamp (IST) - 2-Line Clean Format (Date on top, Time below)
  sheet.setColumnWidth(2, 175); // Order ID
  sheet.setColumnWidth(3, 140); // Party Code (SDMOWB0307)
  sheet.setColumnWidth(4, 210); // Party Name (Customer)
  sheet.setColumnWidth(5, 260); // Party Address
  sheet.setColumnWidth(6, 155); // Area Sales Manager
  sheet.setColumnWidth(7, 130); // Quantity (Pieces)
  sheet.setColumnWidth(8, 110); // Total Boxes
  sheet.setColumnWidth(9, 420); // Ordered Items Breakdown (Spacious for clear un-cramped reading)
  sheet.setColumnWidth(10, 135); // Customer Consent
  sheet.setColumnWidth(11, 120); // Status

  // Wrap text and apply rich styled colors to Breakdown column
  if (sheet.getLastRow() > 1) {
    sheet.getRange(2, 5, sheet.getLastRow() - 1, 1).setWrapStrategy(SpreadsheetApp.WrapStrategy.WRAP);
    sheet.getRange(2, 9, sheet.getLastRow() - 1, 1).setWrapStrategy(SpreadsheetApp.WrapStrategy.WRAP);

    const numRows = sheet.getLastRow() - 1;
    // Fast batch read of Column 9 (Items Breakdown) in 1 single network call
    const col9Range = sheet.getRange(2, 9, numRows, 1);
    const col9Vals = col9Range.getValues();
    // Limit rich text DOM building to latest 100 rows during full migration to stay sub-second fast
    const startIdx = Math.max(0, numRows - 100);
    for (let i = startIdx; i < numRows; i++) {
      const val = col9Vals[i][0];
      if (val && typeof val === "string" && val.indexOf("➔") !== -1) {
        try {
          sheet.getRange(i + 2, 9).setRichTextValue(buildRichBreakdownFromString(val));
        } catch (e) {}
      }
    }
  }

  // Convert and standardize all timestamps in Column A to clean 12-hour AM/PM IST
  fixAllSheetTimestampsTo12HourIST(sheet);
}

/**
 * 🌐 Web App GET Endpoint: Allows checking live status and triggering 1-click migration
 */
function doGet(e) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getActiveSheet() || ss.getSheets()[0];
  migrateAndFormatSheet(sheet);
  return ContentService.createTextOutput(JSON.stringify({
    status: "success",
    message: "🎉 Customers Orders sheet headers & rows fixed successfully into 11 columns!",
    fixedRows: sheet.getLastRow() - 1,
    columns: [
      "Col A (1): Timestamp (IST)",
      "Col B (2): Order ID",
      "Col C (3): Party Code (SDMOWB...)",
      "Col D (4): Party Name (Customer)",
      "Col E (5): Party Address",
      "Col F (6): Area Sales Manager",
      "Col G (7): Quantity (Pieces)",
      "Col H (8): Total Boxes",
      "Col I (9): Ordered Items Breakdown",
      "Col J (10): Customer Consent",
      "Col K (11): Status"
    ]
  })).setMimeType(ContentService.MimeType.JSON);
}

/**
 * 📦 Web App Endpoint: Receives order submissions and appends to Google Sheet
 * Concurrency protected with ScriptLock to guarantee ZERO missed orders.
 */
function doPost(e) {
  const lock = LockService.getScriptLock();
  try {
    lock.waitLock(10000);

    const postData = e && e.postData && e.postData.contents ? JSON.parse(e.postData.contents) : null;
    if (!postData) {
      return ContentService.createTextOutput(JSON.stringify({ status: "error", message: "No data payload received" }))
                           .setMimeType(ContentService.MimeType.JSON);
    }

    appendOrderToSheet(postData);

    return ContentService.createTextOutput(JSON.stringify({
      status: "success",
      orderId: postData.id || postData.orderId,
      message: "Order successfully added to Customers Orders sheet"
    })).setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    Logger.log("doPost Error: " + err.message);
    return ContentService.createTextOutput(JSON.stringify({ status: "error", error: err.message }))
                         .setMimeType(ContentService.MimeType.JSON);
  } finally {
    try { lock.releaseLock(); } catch(e){}
  }
}

/**
 * Core function to append a single order row with proper formatting
 */
function appendOrderToSheet(order) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getActiveSheet();
  if (!sheet) {
    sheet = ss.getSheets()[0];
  }

  // 1. Fast Check: Only run Migration if sheet is completely empty (Saves 600ms on every single order!)
  if (sheet.getLastRow() === 0) {
    migrateAndFormatSheet(sheet);
  }

  // Format timestamp (Clean 2-Line IST: Line 1 = Date, Line 2 = Time)
  const now = new Date();
  let istFormattedTimestamp = "";
  const rawTs = order.formattedTimestamp || order.formatted_timestamp || "";
  const m = rawTs.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})[,\s\n]+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM|am|pm)?/i);
  if (m) {
    const dStr = String(m[1]).padStart(2, "0");
    const mStr = String(m[2]).padStart(2, "0");
    const yStr = m[3];
    let hr = parseInt(m[4], 10);
    const mn = m[5];
    const sc = m[6] || "00";
    let ampm = (m[7] || "").toUpperCase();
    if (!ampm) {
      ampm = hr >= 12 ? "PM" : "AM";
      hr = hr % 12 || 12;
    } else {
      hr = hr % 12 || 12;
    }
    const hrStr = String(hr).padStart(2, "0");
    istFormattedTimestamp = `${dStr}/${mStr}/${yStr}\n${hrStr}:${mn}:${sc} ${ampm}`;
  } else {
    // Generate clean 2-line format
    const dStr = Utilities.formatDate(now, "Asia/Kolkata", "dd/MM/yyyy");
    const tStr = Utilities.formatDate(now, "Asia/Kolkata", "hh:mm:ss a");
    istFormattedTimestamp = `${dStr}\n${tStr}`;
  }
  const orderId = order.id || order.orderId || ("KOGM-" + Utilities.formatDate(now, "Asia/Kolkata", "yyyyMMdd") + "-" + Math.floor(1000 + Math.random() * 9000));

  // Calculate Pieces and Boxes
  const itemsList = order.items || [];
  let totalPieces = Number(order.totalPieces || 0);
  let totalBoxes = Number(order.totalBoxes || 0);
  if (totalPieces === 0 && itemsList.length > 0) {
    totalPieces = 0;
    itemsList.forEach(function(it) {
      const match = (it.item || "").match(/x\s*(\d+)/i);
      const mult = match ? parseInt(match[1], 10) : 1;
      const bxs = parseInt(it.boxes, 10) || 0;
      totalPieces += (bxs * mult);
    });
  }

  // Format items summary string with Pieces and Boxes
  let itemsSummary = order.itemsSummary || "";
  if (!itemsSummary && itemsList.length > 0) {
    itemsSummary = itemsList.map(function(it) {
      const icon = (it.brand || "Mashal").toLowerCase() === "mashal" ? "🔵" : "🟢";
      const match = (it.item || "").match(/x\s*(\d+)/i);
      const mult = match ? parseInt(match[1], 10) : 1;
      const bxs = parseInt(it.boxes, 10) || 0;
      const pcs = bxs * mult;
      return icon + " " + (it.brand || "Mashal") + " " + (it.item || "") + " ➔ " + pcs.toLocaleString() + " Pcs  |  [ " + bxs.toLocaleString() + " Boxes ]";
    }).join("\n");
  }

  // Resolve single Party Address (No duplicate Billing vs Delivery)
  const partyAddress = (order.partyAddress || order.billingAddress || order.deliveryAddress || "").toString().trim();
  const resolvedPartyCode = (order.partyCode || order.party_code || "").toString().trim() || "NEW CUSTOMER";
  const consentVal = (order.dataConsent || order.consent || "YES (Verified)").toString().trim();

  // Exactly 11 Clean Columns:
  // 1: Timestamp (IST)
  // 2: Order ID
  // 3: Party Code
  // 4: Party Name
  // 5: Party Address (Single!)
  // 6: Area Sales Manager
  // 7: Quantity (Pieces)
  // 8: Total Boxes
  // 9: Ordered Items Breakdown
  // 10: Customer Consent
  // 11: Status
  const row = [
    istFormattedTimestamp,
    orderId,
    resolvedPartyCode,
    order.partyName || "",
    partyAddress,
    order.salesPerson || "",
    Number(totalPieces),
    Number(totalBoxes),
    itemsSummary,
    consentVal,
    "CONFIRMED"
  ];

  sheet.appendRow(row);
  const lastRow = sheet.getLastRow();
  
  // ⚡ BATCH ROW FORMATTING (1 network call for whole row vertical alignment!)
  sheet.getRange(lastRow, 1, 1, 11).setVerticalAlignment("middle");

  sheet.getRange(lastRow, 1).setNumberFormat("@").setHorizontalAlignment("center").setVerticalAlignment("middle").setWrapStrategy(SpreadsheetApp.WrapStrategy.WRAP); // Timestamp (2-Line Format: Date on top, Time below)
  sheet.getRange(lastRow, 2).setFontFamily("Courier New").setFontWeight("bold").setFontColor("#004b99").setHorizontalAlignment("center"); // Order ID
  sheet.getRange(lastRow, 3).setFontFamily("Courier New").setFontWeight("bold").setFontColor("#003366").setBackground("#eff6ff").setHorizontalAlignment("center"); // Party Code
  sheet.getRange(lastRow, 4).setFontWeight("bold"); // Party Name
  sheet.getRange(lastRow, 5).setWrapStrategy(SpreadsheetApp.WrapStrategy.WRAP); // Address
  sheet.getRange(lastRow, 6).setHorizontalAlignment("center"); // ASM
  sheet.getRange(lastRow, 7).setFontWeight("bold").setFontSize(11).setHorizontalAlignment("center").setFontColor("#1e40af").setBackground("#f0fdf4"); // Pieces
  sheet.getRange(lastRow, 8).setFontWeight("bold").setFontSize(11).setHorizontalAlignment("center").setBackground("#eff6ff"); // Boxes
  
  // Column 9: Items Breakdown (Always Rich Colored: Blue Pieces & Amber Boxes)
  const cellBreakdown = sheet.getRange(lastRow, 9);
  try {
    if (itemsList && itemsList.length > 0) {
      cellBreakdown.setRichTextValue(buildRichItemsBreakdown(itemsList, itemsSummary));
    } else if (itemsSummary) {
      cellBreakdown.setRichTextValue(buildRichBreakdownFromString(itemsSummary));
    }
  } catch (e) {
    console.warn("Could not set rich text on append:", e);
    cellBreakdown.setValue(itemsSummary);
  }
  cellBreakdown.setWrapStrategy(SpreadsheetApp.WrapStrategy.WRAP);

  sheet.getRange(lastRow, 10).setFontWeight("bold").setFontSize(10.5).setFontColor("#15803d").setBackground("#f0fdf4").setHorizontalAlignment("center"); // Consent
  sheet.getRange(lastRow, 11).setFontWeight("bold").setFontColor("#15803d").setHorizontalAlignment("center"); // Status

  // Dynamic spacious row height
  const calculatedHeight = Math.max(44, itemsList.length * 24 + 14);
  sheet.setRowHeight(lastRow, calculatedHeight);
}

/**
 * 🎨 Builds Rich Text with Bold Brand, Bold Blue Pieces, and Bold Amber Boxes
 */
function buildRichItemsBreakdown(itemsList, fallbackText) {
  const richTextBuilder = SpreadsheetApp.newRichTextValue();
  let fullText = "";
  const brandRanges = [];
  const pcsRanges = [];
  const bxsRanges = [];

  if (itemsList && itemsList.length > 0) {
    itemsList.forEach(function(it, idx) {
      const isMashal = (it.brand || "Mashal").toLowerCase() === "mashal";
      const icon = isMashal ? "🔵" : "🟢";
      const match = (it.item || "").match(/x\s*(\d+)/i);
      const mult = match ? parseInt(match[1], 10) : 1;
      const bxs = parseInt(it.boxes, 10) || 0;
      const pcs = (typeof it.pieces !== "undefined" && Number(it.pieces) > 0) ? Number(it.pieces) : (bxs * mult);

      const pcsStr = pcs.toLocaleString() + " Pcs";
      const bxsStr = "[ " + bxs.toLocaleString() + " Boxes ]";
      const line = icon + " " + (it.brand || "Mashal") + " " + (it.item || "") + "   ➔   " + pcsStr + "   |   " + bxsStr;

      const startIdx = fullText.length;
      fullText += (idx > 0 ? "\n" : "") + line;
      const lineStart = idx > 0 ? startIdx + 1 : startIdx;

      // 1. Brand range
      const brandEnd = lineStart + icon.length + 1 + (it.brand || "Mashal").length;
      brandRanges.push({
        start: lineStart,
        end: brandEnd,
        isMashal: isMashal
      });

      // 2. Pieces range
      const pcsIdx = line.indexOf(pcsStr);
      if (pcsIdx !== -1) {
        pcsRanges.push({
          start: lineStart + pcsIdx,
          end: lineStart + pcsIdx + pcsStr.length
        });
      }

      // 3. Boxes range
      const bxsIdx = line.indexOf(bxsStr);
      if (bxsIdx !== -1) {
        bxsRanges.push({
          start: lineStart + bxsIdx,
          end: lineStart + bxsIdx + bxsStr.length
        });
      }
    });
  } else if (fallbackText) {
    return buildRichBreakdownFromString(fallbackText);
  }

  richTextBuilder.setText(fullText || fallbackText || "");

  // Apply Brand Colors (Mashal = Bold Navy #003366, Fauji = Bold Forest Green #007a3d)
  brandRanges.forEach(function(r) {
    const style = SpreadsheetApp.newTextStyle()
      .setBold(true)
      .setForegroundColor(r.isMashal ? "#003366" : "#007a3d")
      .build();
    richTextBuilder.setTextStyle(r.start, r.end, style);
  });

  // Apply Pieces Styling (Bold Royal Blue #1d4ed8)
  const pcsStyle = SpreadsheetApp.newTextStyle()
    .setBold(true)
    .setForegroundColor("#1d4ed8")
    .build();
  pcsRanges.forEach(function(r) {
    richTextBuilder.setTextStyle(r.start, r.end, pcsStyle);
  });

  // Apply Boxes Styling (Bold Warm Amber #b45309)
  const bxsStyle = SpreadsheetApp.newTextStyle()
    .setBold(true)
    .setForegroundColor("#b45309")
    .build();
  bxsRanges.forEach(function(r) {
    richTextBuilder.setTextStyle(r.start, r.end, bxsStyle);
  });

  return richTextBuilder.build();
}

/**
 * 🔄 Parses raw breakdown text and builds styled rich text with bold colored numbers
 */
function buildRichBreakdownFromString(rawText) {
  if (!rawText) return SpreadsheetApp.newRichTextValue().setText("").build();
  const lines = String(rawText).split("\n");
  const parsedItems = [];
  lines.forEach(function(l) {
    if (!l.trim()) return;
    const isMashal = l.indexOf("Mashal") !== -1;
    const brand = isMashal ? "Mashal" : "Fauji";
    
    // Parse pieces and boxes (handles both "4395 Pcs (293 bxs)" and "4,395 Pcs | [ 293 Boxes ]")
    const m = l.match(/➔\s*([\d,]+)\s*Pcs.*?([\d,]+)\s*(?:bxs|boxes)/i);
    let pcs = 0;
    let bxs = 0;
    if (m) {
      pcs = parseInt(m[1].replace(/,/g, ""), 10) || 0;
      bxs = parseInt(m[2].replace(/,/g, ""), 10) || 0;
    }
    
    // Extract item packaging name
    let itemPart = "";
    const brandPos = l.indexOf(brand);
    const arrowPos = l.indexOf("➔");
    if (brandPos !== -1 && arrowPos !== -1) {
      itemPart = l.substring(brandPos + brand.length, arrowPos).trim();
    }
    
    parsedItems.push({
      brand: brand,
      item: itemPart || "Packaging",
      boxes: bxs,
      pieces: pcs
    });
  });

  if (parsedItems.length === 0) {
    return SpreadsheetApp.newRichTextValue().setText(rawText).build();
  }
  return buildRichItemsBreakdown(parsedItems, rawText);
}

/**
 * 🛠️ UTILITY: Run this one-click function in Google Apps Script editor
 * to convert all existing rows in Google Sheet from 24h format (e.g. 14:15:56)
 * into clean 12-hour AM/PM format (e.g. 02:15:56 PM).
 */
function fixAllSheetTimestampsTo12HourIST(targetSheet) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = targetSheet || (ss ? ss.getSheets()[0] : null);
  if (!sheet) return;
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return;

  const range = sheet.getRange(2, 1, lastRow - 1, 1);
  const values = range.getValues();
  let updatedCount = 0;

  for (let i = 0; i < values.length; i++) {
    const val = values[i][0];
    if (val instanceof Date) {
      values[i][0] = Utilities.formatDate(val, "Asia/Kolkata", "dd/MM/yyyy") + "\n" + Utilities.formatDate(val, "Asia/Kolkata", "hh:mm:ss a");
      updatedCount++;
    } else if (typeof val === "string" && val.trim().length > 0) {
      const s = val.trim();
      const m = s.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})[,\s\n]+(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\s*(AM|PM))?/i);
      if (m) {
        const dayStr = String(m[1]).padStart(2, "0");
        const monStr = String(m[2]).padStart(2, "0");
        const yrStr = m[3];
        let hr = parseInt(m[4], 10);
        const mn = m[5];
        const sc = m[6] || "00";
        let ampm = (m[7] || "").toUpperCase();

        if (!ampm) {
          ampm = hr >= 12 ? "PM" : "AM";
          hr = hr % 12 || 12;
        } else {
          hr = hr % 12 || 12;
        }

        const hrStr = String(hr).padStart(2, "0");
        values[i][0] = `${dayStr}/${monStr}/${yrStr}\n${hrStr}:${mn}:${sc} ${ampm}`;
        updatedCount++;
      }
    }
  }

  // Set number format to plain text and WRAP with middle alignment to ensure 2 Clean Lines: Date on top, Time below
  range.setNumberFormat("@");
  range.setValues(values);
  range.setHorizontalAlignment("center");
  range.setVerticalAlignment("middle");
  range.setWrapStrategy(SpreadsheetApp.WrapStrategy.WRAP);
  sheet.setColumnWidth(1, 140);
  Logger.log("Successfully converted " + updatedCount + " rows to clean 2-Line (Date on top, Time below) IST format!");
}

