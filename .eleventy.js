const { parse } = require("csv-parse/sync");
const { diffWords } = require("diff")

module.exports = function(eleventyConfig) {
    eleventyConfig.addLiquidFilter("diff", function(a, b) { return diffWords(a || '', b || '') });
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
    eleventyConfig.addLiquidFilter("where_in", function(arr1, key, arr2) {
        return arr1.filter((e) => arr2.includes(e[key]))
    });
    eleventyConfig.addDataExtension("csv", (contents) => {
        const records = parse(contents, {
            cast: function(value) {
                try {
                    return JSON.parse(value)
                } catch {
                    if (value == 'NULL') return null
                    return value
                }
            },
            columns: true,
            skip_empty_lines: true,
        });
        return records;
    });
};