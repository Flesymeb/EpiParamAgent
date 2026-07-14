import { useEffect, useMemo, useRef, useState } from "react"
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table"
import type {
  CellContext,
  ColumnDef,
  RowData,
} from "@tanstack/react-table"
import {
  SearchIcon,
  XIcon,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { cn } from "@/lib/utils"

type EditableRow = Record<string, string>
type EditableTableRow = {
  sourceIndex: number
  values: EditableRow
}

type EditableTableProps = {
  columns: string[]
  rows: EditableRow[]
  onChange: (rows: EditableRow[]) => void
}

declare module "@tanstack/react-table" {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface TableMeta<TData extends RowData> {
    updateData: (
      rowIndex: number,
      columnId: string,
      value: string
    ) => void
  }

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<TData extends RowData, TValue> {
    sourceColumn?: string
  }
}

export function EditableTable({
  columns,
  rows,
  onChange,
}: EditableTableProps) {
  const [data, setData] = useState<EditableRow[]>(() =>
    normalizeRows(rows, columns)
  )
  const [query, setQuery] = useState("")
  const normalizedQuery = query.trim().toLowerCase()

  const visibleData = useMemo<EditableTableRow[]>(() => {
    return data
      .map((row, index) => ({ sourceIndex: index, values: row }))
      .filter((row) => {
        if (!normalizedQuery) {
          return true
        }

        return columns.some((column) =>
          normalizeCellValue(row.values[column])
            .toLowerCase()
            .includes(normalizedQuery)
        )
      })
  }, [columns, data, normalizedQuery])

  const columnDefs = useMemo<ColumnDef<EditableTableRow>[]>(
    () =>
      columns.map((column, index) => ({
        accessorFn: (row) => row.values[column],
        header: column || `Column ${index + 1}`,
        id: column || `column-${index + 1}`,
        meta: { sourceColumn: column },
        cell: EditableCell,
      })),
    [columns]
  )
  const tableShapeKey = `${columns.join("\u0000")}:${visibleData.length}`
  const { canScrollRight, ref: tableScrollRef } =
    useHorizontalScrollHints(tableShapeKey)

  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: visibleData,
    columns: columnDefs,
    getRowId: (row) => String(row.sourceIndex),
    getCoreRowModel: getCoreRowModel(),
    meta: {
      updateData: (rowIndex, columnId, value) => {
        setData((current) => {
          const next = current.map((row, index) =>
            index === rowIndex ? { ...row, [columnId]: value } : row
          )
          onChange(next)
          return next
        })
      },
    },
  })

  return (
    <div className="w-full min-w-0 max-w-full space-y-2">
      <div className="flex flex-col items-stretch gap-2 rounded-lg border border-border/70 bg-muted/15 px-2 py-2 sm:flex-row sm:items-center sm:px-3 sm:py-2.5">
        <div className="min-w-0 shrink-0 text-[0.7rem] leading-4 text-muted-foreground sm:text-xs">
          <span className="sm:hidden">
            <span className="font-medium text-foreground">
              {visibleData.length}
            </span>
            /{data.length} rows
            <span className="mx-1 text-border">/</span>
            {columns.length} fields
          </span>
          <span className="hidden sm:inline">
            <span className="font-medium text-foreground">
              {visibleData.length}
            </span>{" "}
            of {data.length} rows
            <span className="mx-1 text-border">/</span>
            {columns.length} fields
          </span>
        </div>
        <div className="relative min-w-0 w-full sm:w-80 sm:flex-none">
          <SearchIcon className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            aria-label="Search table rows"
            className="h-8 bg-background pl-8 pr-8 text-sm"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search rows"
            value={query}
          />
          {query ? (
            <Button
              aria-label="Clear table search"
              className="absolute right-0.5 top-0.5"
              onClick={() => setQuery("")}
              size="icon-sm"
              type="button"
              variant="ghost"
            >
              <XIcon />
            </Button>
          ) : null}
        </div>
      </div>
      <div className="relative w-full min-w-0 max-w-full">
        <div
          className="max-h-[min(46vh,420px)] w-full min-w-0 max-w-full overflow-auto overscroll-contain rounded-lg border border-border/80 bg-card shadow-xs sm:max-h-[min(60vh,560px)]"
          ref={tableScrollRef}
        >
          <Table className="w-max min-w-full" unwrapped>
            <TableHeader className="bg-muted/95" sticky>
              {table.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id}>
                  <TableHead className="sticky left-0 z-50! w-12 min-w-12 max-w-12 bg-muted text-center shadow-[1px_0_0_var(--border)]">
                    #
                  </TableHead>
                  {headerGroup.headers.map((header, index) => (
                    <TableHead
                      className={cn(
                        "min-w-44 max-w-72 whitespace-normal align-top",
                        index === 0 &&
                          "sticky left-12 z-40! bg-muted shadow-[1px_0_0_var(--border)]"
                      )}
                      key={header.id}
                    >
                      {header.isPlaceholder
                        ? null
                        : flexRender(
                            header.column.columnDef.header,
                            header.getContext()
                          )}
                    </TableHead>
                  ))}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {table.getRowModel().rows.length > 0 ? (
                table.getRowModel().rows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell
                      className="sticky left-0 z-30 w-12 min-w-12 max-w-12 bg-card px-2 text-center font-mono text-xs text-muted-foreground shadow-[1px_0_0_var(--border)]"
                      title={`Row ${row.original.sourceIndex + 1}`}
                    >
                      {row.original.sourceIndex + 1}
                    </TableCell>
                    {row.getVisibleCells().map((cell, index) => (
                      <TableCell
                        className={cn(
                          "min-w-44 max-w-80 whitespace-normal p-1 align-top",
                          index === 0 &&
                            "sticky left-12 z-20 bg-card shadow-[1px_0_0_var(--border)]"
                        )}
                        key={cell.id}
                      >
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell
                    className="h-24 text-center text-sm text-muted-foreground"
                    colSpan={(columns.length || 1) + 1}
                  >
                    {query ? "No matching rows." : "No rows."}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
        {canScrollRight ? (
          <div
            aria-hidden="true"
            className="pointer-events-none absolute bottom-px right-px top-px z-50 w-8 rounded-r-lg bg-gradient-to-l from-card via-card/85 to-transparent"
          />
        ) : null}
      </div>
    </div>
  )
}

function EditableCell({
  getValue,
  row,
  column,
  table,
}: CellContext<EditableTableRow, unknown>) {
  const initialValue = normalizeCellValue(getValue())
  const sourceColumn = column.columnDef.meta?.sourceColumn ?? column.id

  return (
    <Input
      aria-label={`${sourceColumn || column.id} row ${row.original.sourceIndex + 1}`}
      className={cn(
        "h-8 min-w-40 rounded-md border-transparent bg-transparent px-2",
        "font-mono text-xs focus-visible:border-ring"
      )}
      defaultValue={initialValue}
      onBlur={(event) =>
        table.options.meta?.updateData(
          row.original.sourceIndex,
          sourceColumn,
          event.currentTarget.value
        )
      }
    />
  )
}

function normalizeRows(rows: EditableRow[], columns: string[]) {
  return rows.map((row) => {
    const normalized: EditableRow = {}
    columns.forEach((column) => {
      normalized[column] = normalizeCellValue(row[column])
    })
    return normalized
  })
}

function normalizeCellValue(value: unknown) {
  return typeof value === "string" ? value : String(value ?? "")
}

function useHorizontalScrollHints(dependencyKey: string) {
  const ref = useRef<HTMLDivElement>(null)
  const [canScrollRight, setCanScrollRight] = useState(false)

  useEffect(() => {
    const node = ref.current
    if (!node) {
      return
    }

    const update = () => {
      const maxScrollLeft = node.scrollWidth - node.clientWidth
      setCanScrollRight(node.scrollLeft < maxScrollLeft - 1)
    }

    update()
    const resizeObserver = new ResizeObserver(update)
    resizeObserver.observe(node)
    node.addEventListener("scroll", update, { passive: true })
    window.addEventListener("resize", update)

    return () => {
      resizeObserver.disconnect()
      node.removeEventListener("scroll", update)
      window.removeEventListener("resize", update)
    }
  }, [dependencyKey])

  return { canScrollRight, ref }
}
