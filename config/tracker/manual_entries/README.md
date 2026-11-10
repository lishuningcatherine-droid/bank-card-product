# Manual campaign entries

Entries for offers the pipeline could not read automatically (pages that changed layout, robots-disallowed pages,
targeted or branch offers). Each file is entered with `bankrec offers add <file> --by <name>` and stays **pending
review** until someone other than the person who entered it runs `bankrec offers approve <id>`. Every excerpt is copied
verbatim from the capture named in the file.
