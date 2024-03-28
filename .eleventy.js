const { parse } = require("csv-parse/sync");
const { diffWords } = require("diff");

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
    eleventyConfig.addFilter("diff", function(a, b) { return diffWords(a || '', b || '') });
    eleventyConfig.addFilter("find", function(arr, key, value) { return arr.find((obj) => obj[key] == value) });
    eleventyConfig.addFilter("where", function(arr, key, test, value) { return arr.filter((obj) => value ? obj[key][test].bind(obj[key])(value) : obj[key] == test )});
    eleventyConfig.addFilter("map", function(arr, key) { return Array.isArray(arr) ? arr.map((obj) => obj[key]) : arr[key] });
    eleventyConfig.addFilter("where_in", function(arr1, key, arr2) { return arr1.filter((e) => arr2.includes(e[key])) });
    eleventyConfig.addFilter("current", function(arr, date) {
        return arr.map((member) => {
            current = getCurrent(member.constituencies, date || new Date().toISOString())
            if (!current) return false
            return { ...member, ...current }
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
            //to: 100,
        });
        return records;
    });
};
