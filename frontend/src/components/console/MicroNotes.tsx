import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Plus } from "lucide-react";
import { toast } from "sonner";

interface MicroNotesProps {
  defaultSymbol: string;
}

interface Note {
  id: number;
  symbol: string;
  text: string;
  tag: "Plan" | "Adjust" | "Emotion";
  timestamp: Date;
}

export const MicroNotes = ({ defaultSymbol }: MicroNotesProps) => {
  const [noteText, setNoteText] = useState("");
  const [noteTag, setNoteTag] = useState<"Plan" | "Adjust" | "Emotion">("Plan");
  const [notes, setNotes] = useState<Note[]>([
    {
      id: 1,
      symbol: defaultSymbol,
      text: "Watching for break of PDH at 433.50",
      tag: "Plan",
      timestamp: new Date(Date.now() - 1000 * 60 * 15),
    },
    {
      id: 2,
      symbol: defaultSymbol,
      text: "Tightened stop to breakeven",
      tag: "Adjust",
      timestamp: new Date(Date.now() - 1000 * 60 * 30),
    },
  ]);

  const handleAddNote = () => {
    if (!noteText.trim()) {
      toast.error("Note text is required");
      return;
    }

    const newNote = {
      id: Date.now(),
      symbol: defaultSymbol,
      text: noteText,
      tag: noteTag,
      timestamp: new Date(),
    };

    setNotes([newNote, ...notes]);
    setNoteText("");
    toast.success("Note added");
  };

  const getTagColor = (tag: string) => {
    switch (tag) {
      case "Plan":
        return "bg-primary/10 text-primary border-primary/20";
      case "Adjust":
        return "bg-warning/10 text-warning border-warning/20";
      case "Emotion":
        return "bg-destructive/10 text-destructive border-destructive/20";
      default:
        return "bg-muted text-muted-foreground";
    }
  };

  const symbolNotes = notes.filter(n => n.symbol === defaultSymbol).slice(0, 3);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Quick Notes - {defaultSymbol}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Add Note Form */}
        <div className="space-y-2">
          <Input
            placeholder="Quick note..."
            value={noteText}
            onChange={(e) => setNoteText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                handleAddNote();
              }
            }}
            className="text-sm"
          />
          <div className="flex gap-2">
            <Select value={noteTag} onValueChange={(v) => setNoteTag(v as any)}>
              <SelectTrigger className="text-xs h-8">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="Plan">Plan</SelectItem>
                <SelectItem value="Adjust">Adjust</SelectItem>
                <SelectItem value="Emotion">Emotion</SelectItem>
              </SelectContent>
            </Select>
            <Button onClick={handleAddNote} size="sm" className="h-8">
              <Plus className="h-3 w-3 mr-1" />
              Add
            </Button>
          </div>
        </div>

        {/* Recent Notes */}
        <div className="space-y-2">
          {symbolNotes.length === 0 ? (
            <p className="text-xs text-muted-foreground text-center py-4">No notes for this symbol yet.</p>
          ) : (
            symbolNotes.map((note) => (
              <div key={note.id} className="p-2 border border-border rounded text-xs space-y-1">
                <div className="flex items-center justify-between">
                  <Badge className={`text-xs ${getTagColor(note.tag)}`}>{note.tag}</Badge>
                  <span className="text-muted-foreground">
                    {note.timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  </span>
                </div>
                <p className="text-foreground">{note.text}</p>
              </div>
            ))
          )}
        </div>
      </CardContent>
    </Card>
  );
};
