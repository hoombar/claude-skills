---
name: mermaid-to-png
description: Saves a Mermaid diagram as a PNG image. Use when discussing mermaid diagrams and the user asks to save it as an image.
---

Save a Mermaid diagram as a PNG to `~/Desktop/mermaid diagrams/`.

## Steps

1. Write the Mermaid diagram source to a temporary `.mmd` file at `/tmp/mermaid_temp.mmd`.
2. Generate a random filename using a short descriptive prefix based on the diagram content plus a random suffix, e.g. `flow-a3f9b2`. Do NOT ask the user for a filename.
3. Copy the `.mmd` source file to the output folder with the same base name:
   ```
   cp /tmp/mermaid_temp.mmd "$HOME/Desktop/mermaid diagrams/<filename>.mmd"
   ```
4. Run mmdc to convert:
   ```
   mmdc -i /tmp/mermaid_temp.mmd -o "$HOME/Desktop/mermaid diagrams/<filename>.png" -b transparent -s 2
   ```
5. Verify both output files were created successfully.
6. Clean up the temp file.
7. Tell the user the filename and provide a clickable link to open the containing folder:
   ```
   [Open folder](file:///Users/ben.pearson/Desktop/mermaid%20diagrams)
   ```

## Notes

- The diagram source should come from the current conversation context or from a file the user points to.
- If the diagram has parse errors, fix them before converting.
- Use scale factor `-s 2` for crisp output by default.
- If the user wants a different background, use `-b white` or whatever they request instead of transparent.
