const { parse } = require("csv-parse/sync");
const DiffMatchPatch = require('diff-match-patch');

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
        lineEnd = text.indexOf(' ', lineStart);
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

function party_from_str(s) {
    switch (s) {
        case "Agir - La Droite constructive":
        case "Liste Renaissance":
        case "La République en marche":
        case "Liste L'Europe Ensemble":
            return "Renaissance"
        case 'Mouvement Radical Social-Libéral':
            return "Parti Radical"
        default:
            return s
    }
}

function getCurrent(arr, date) {
    return arr.find((c) => c.start < date && date < c.end)
}

module.exports = function(eleventyConfig) {
    eleventyConfig.addFilter("date", (dateString) => new Date(dateString).toLocaleDateString('fr-FR', { year: 'numeric', month: 'long', day: 'numeric' }));
    eleventyConfig.addFilter("diff", function(text1, text2) {
        var a = dmp.diff_linesToWords_(text1 || '', text2 || '');
        var lineText1 = a.chars1;
        var lineText2 = a.chars2;
        var lineArray = a.lineArray;
        let diffs = dmp.diff_main(lineText1, lineText2, false);
        dmp.diff_charsToLines_(diffs, lineArray);
        dmp.diff_cleanupSemantic(diffs);
        return diffs;
    });
    eleventyConfig.addFilter("find", function(arr, key, value) { return arr.find((obj) => value ? obj[key] == value : obj[key]) });
    eleventyConfig.addFilter("where", function(arr, key, test, value) { return arr.filter((obj) => value ? obj[key][test].bind(obj[key])(value) : obj[key] == test )});
    eleventyConfig.addFilter("map", function(arr, key) { return Array.isArray(arr) ? arr.map((obj) => obj[key]) : arr[key] });
    eleventyConfig.addFilter("where_in", function(arr1, key, arr2) { return arr1.filter((e) => arr2.includes(e[key])) });
    eleventyConfig.addFilter("current", function(arr, date) {
        return arr.map((member) => {
            current = getCurrent(member.constituencies, date || new Date().toISOString())
            if (!current) return false
            return { ...member, ...current, party: party_from_str(current.party) }
        }).filter(Boolean)
    });
    eleventyConfig.addFilter("attendance", function(atts, member) {
        return atts.filter((att) => {
            current = getCurrent(member.constituencies, att.date)
            if (!current) return false
            return att.member_id == member.id && current.start < att.date && att.date < current.end
        })
    });
    eleventyConfig.addFilter("ratio", (a, b) => (a / b * 100).toFixed(1) + '%');

    eleventyConfig.addLiquidFilter("startswith", function(str, value) { return str.startsWith(value) });
    
    eleventyConfig.addLiquidFilter("where_exp", function(arr, key, cond) {
        return arr.filter((el) => eval(`const { ${key} } = el; ${cond}`))
    });
    eleventyConfig.addLiquidFilter("groupby_exp", function(arr, key, cond) {
        return arr.reduce(
            (groups, obj) => {
                const res = eval(`const { ${key} } = obj; ${cond}`)
                const group = groups.find((g) => g.name == res)
                if (group) group.items.push(obj)
                else groups.push({ name: res, items: [obj] })
                return groups
            },
            []
        )
    });
    eleventyConfig.addLiquidFilter("dot", function(obj, path) { return path.split('.').reduce((a, b) => a[b], obj);});
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

    eleventyConfig.addDataExtension("csv", (contents) => {
        const records = parse(contents, {
            cast: function(value) {
                try {
                    return JSON.parse(value)
                } catch {
                    if (value == 'NULL') return null
                    if (value.toLowerCase() == 'true') return true
                    if (value.toLowerCase() == 'false') return false
                    return value
                }
            },
            columns: true,
            relax_quotes: true,
            skip_empty_lines: true,
        });
        return records;
    });
};
