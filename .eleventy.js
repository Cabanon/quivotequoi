const { parse } = require("csv-parse/sync");
const DiffMatchPatch = require('diff-match-patch');

function regexIndexOf(string, regex, startpos) {
    var indexOf = string.substring(startpos || 0).normalize('NFD').replace(/[\u0300-\u036f]/g, '').search(regex);
    return (indexOf >= 0) ? (indexOf + (startpos || 0)) : indexOf;
}

DiffMatchPatch.prototype.diff_linesToWords_ = function(text1, text2) {
    var lineArray = [];  // e.g. lineArray[4] == 'Hello\n'
    var lineHash = {};   // e.g. lineHash['Hello\n'] == 4
  
    // '\x00' is a valid character, but various debuggers don't like it.
    // So we'll insert a junk entry to avoid generating a null character.
    lineArray[0] = '';
  
    /**
     * Split a text into an array of strings.  Reduce the texts to a string of
     * hashes where each Unicode character represents one line.
     * Modifies linearray and linehash through being a closure.
     * @param {string} text String to encode.
     * @return {string} Encoded string.
     * @private
     */
    function diff_linesToCharsMunge_(text) {
      var chars = '';
      // Walk the text, pulling out a substring for each line.
      // text.split('\n') would would temporarily double our memory footprint.
      // Modifying text would create many large strings to garbage collect.
      var lineStart = 0;
      var lineEnd = -1;
      // Keeping our own length variable is faster than looking it up.
      var lineArrayLength = lineArray.length;
      while (lineEnd < text.length - 1) {
        lineEnd = regexIndexOf(text, /.\b/, lineStart);
        if (lineEnd == -1) {
          lineEnd = text.length - 1;
        }
        var line = text.substring(lineStart, lineEnd + 1);
  
        if (lineHash.hasOwnProperty ? lineHash.hasOwnProperty(line) :
            (lineHash[line] !== undefined)) {
          chars += String.fromCharCode(lineHash[line]);
        } else {
          if (lineArrayLength == maxLines) {
            // Bail out at 65535 because
            // String.fromCharCode(65536) == String.fromCharCode(0)
            line = text.substring(lineStart);
            lineEnd = text.length;
          }
          chars += String.fromCharCode(lineArrayLength);
          lineHash[line] = lineArrayLength;
          lineArray[lineArrayLength++] = line;
        }
        lineStart = lineEnd + 1;
      }
      return chars;
    }
    // Allocate 2/3rds of the space for text1, the rest for text2.
    var maxLines = 40000;
    var chars1 = diff_linesToCharsMunge_(text1);
    maxLines = 65535;
    var chars2 = diff_linesToCharsMunge_(text2);
    return {chars1: chars1, chars2: chars2, lineArray: lineArray};
};

const dmp = new DiffMatchPatch();

function getCurrent(arr, date) {
    return arr.find((c) => c.start < date && date < c.end)
}

module.exports = function(eleventyConfig) {
    // General filters
    eleventyConfig.addFilter("log", (e) => console.log(e))
    eleventyConfig.addFilter("uniq", (arr, key) => key ? [...new Map(arr.map(e => [e[key], e])).values()] : [...new Set(arr)])
    eleventyConfig.addFilter("startswith", function(str, value) { return str.startsWith(value) });
    eleventyConfig.addFilter("where_exp", function(arr, key, cond) {
        return arr.filter((el) => eval(`const { ${key} } = el; ${cond}`))
    });
    eleventyConfig.addFilter("date", (dateString) => new Date(dateString).toLocaleDateString('fr-FR', { year: 'numeric', month: 'long', day: 'numeric' }));
    eleventyConfig.addFilter("diff", function(text1, text2) {
        var a = dmp.diff_linesToWords_(text1 || '', text2 || '');
        var lineText1 = a.chars1;
        var lineText2 = a.chars2;
        var lineArray = a.lineArray;
        let diffs = dmp.diff_main(lineText1, lineText2, false);
        dmp.diff_cleanupSemantic(diffs);
        dmp.diff_charsToLines_(diffs, lineArray);
        dmp.diff_cleanupSemanticLossless(diffs);
        return diffs;
    });
    eleventyConfig.addFilter("intsort", (arr, key) => arr.sort((a, b) => isNaN(a[key]) ? 1 : (isNaN(b[key]) ? -1 : a[key] - b[key])));
    eleventyConfig.addFilter("find", function(arr, key, value) { return arr.find((obj) => value === undefined ? obj[key] : obj[key] == value) });
    eleventyConfig.addFilter("where", (arr, key, test, value) => arr.filter((obj) => test !== undefined ? (value !== undefined ? obj[key][test].bind(obj[key])(value) : obj[key] == test) : obj[key] ));
    eleventyConfig.addFilter("map", function(arr, key) { return Array.isArray(arr) ? arr.map((obj) => obj[key]) : arr[key] });
    eleventyConfig.addFilter("int", function(arr) { return Array.isArray(arr) ? arr.map(i => parseInt(i)) : parseInt(arr) });
    eleventyConfig.addFilter("where_in", (arr1, key, arr2) => arr1.filter((e) => arr2.includes(e[key])));
    eleventyConfig.addFilter("where_includes", (arr1, key, value) => arr1.filter((e) => e[key].includes(value)));
    eleventyConfig.addFilter("map_entries", (obj, key, value) => Object.entries(obj).map(([k, v]) => ({[key]: Number(k), [value]: v})));

    // Data specific filters
    eleventyConfig.addFilter("current", function(arr, date = new Date().toISOString()) {
        func = (member) => {
            const { party, partyid } = getCurrent(member.constituencies, date) || {}
            const { groupid } = getCurrent(member.groups, date) || {}
            if (!(party && groupid)) return false
            return { ...member, group: groupid, party, partyid }
        }
        if (Array.isArray(arr)) {
            return arr.map(func).filter(Boolean)
        }
        return func(arr)
    });
    eleventyConfig.addFilter("position", (position) => {switch (position) { case '+': 'for'; case '-': 'against'; case '0': 'abstention'; default: 'novote' }})
    eleventyConfig.addFilter("attendance", function(atts, member) {
        return atts.filter((att) => {
            current = getCurrent(member.constituencies, att.date)
            if (!current) return false
            return att.member_id == member.id && current.start < att.date && att.date < current.end
        })
    });
    eleventyConfig.addFilter("ratio", (a, b) => (a / b * 100).toFixed(1) + '%');


    eleventyConfig.addLiquidFilter("group_by", function(array, key) {
        return array.reduce(
            (groups, obj) => {
                const group = groups.find((g) => g.name == obj[key])
                if (group) group.items.push(obj)
                else groups.push({ name: obj[key], items: [obj] })
                return groups
            },
            []
        )
    });

    eleventyConfig.addPassthroughCopy("bundle.css");
    eleventyConfig.addPassthroughCopy("favicon.ico");
    eleventyConfig.addPassthroughCopy("robots.txt");
    eleventyConfig.addPassthroughCopy("*.js");

    eleventyConfig.addDataExtension("csv", (contents, filePath) => {
        const records = parse(contents, {
            cast: function(value) {
                try {
                    return JSON.parse(value)
                } catch {
                    if (value == 'False') return false
                    if (value == 'True') return true
                    return value
                }
            },
            columns: true,
            skip_empty_lines: true,
        });
        return records;
    });
};